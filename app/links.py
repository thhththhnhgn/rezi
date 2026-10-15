"""
ULTRA GAMING VPN — share-link + subscription generators.

Outputs
-------
raw       : one URI per line (vless:// vmess:// trojan:// ss://)
base64    : v2rayN / v2rayNG style subscription
clash     : Clash.Meta YAML
singbox   : sing-box 1.9+ JSON with an urltest auto-failover outbound

All links assume the edge terminates TLS on :443 (Railway does).
"""

from __future__ import annotations

import base64
import json
import os
from urllib.parse import quote

from . import db, locations, paths, profiles, reality, xray

# ── smart fragment (anti-DPI) ───────────────────────────────────────────
FRAGMENT_MODES: dict[str, dict | None] = {
    "": None,   # off
    "light": {"packets": "tlshello", "length": "20-40", "interval": "30-60"},
    "medium": {"packets": "tlshello", "length": "10-30", "interval": "20-40"},
    "aggressive": {"packets": "tlshello", "length": "5-15", "interval": "10-25"},
}


def smart_fragment() -> dict | None:
    """Global fragment preset from the smart_fragment DB setting."""
    mode = str(db.get_setting("smart_fragment", "") or "").strip().lower()
    return FRAGMENT_MODES.get(mode)


def fragment_listing() -> list[dict]:
    """The four choices shown in the panel."""
    return [{"id": k, "label": (k or "off")} for k in FRAGMENT_MODES]


def _q(s: str) -> str:
    return quote(str(s), safe="")


def _tag(name: str, kind: str, via: str) -> str:
    return f"{name}-{kind}-{via}"


# ── individual URI builders ──────────────────────────────────────────────────

def vless_uri(user: dict, host: str, network: str, path: str,
              via: str = "Direct", prof: dict | None = None,
              tag: str | None = None, addr: str | None = None) -> str:
    prof = prof or profiles.get(None)

    # Early data: the client puts its first payload inside the upgrade
    # request instead of waiting for the server's reply, which removes one
    # full round trip from every new connection.
    #
    # 2560 is the documented recommendation; larger values break some
    # middleboxes.
    if network in ("ws", "httpupgrade"):
        path = f"{path}?ed=2560"
    params = [
        "encryption=none",
        "security=tls",
        f"sni={host}",
        f"host={host}",
        f"type={network}",
        f"path={_q(path)}",
        # random fingerprint: avoids TLS fingerprinting by ISPs/DPI.
        # h2+http/1.1 ALPN: client picks h2 for multiplexed transfers
        # (XHTTP, parallel downloads) and falls back to http/1.1 elsewhere.
        "fp=random",
        "alpn=h2,http%2F1.1",
    ]

    if network == "xhttp":
        # must match the server's xhttpSettings.mode (see app/xray.py)
        params.append("mode=packet-up")

    # Fragmentation: the per-profile preset (stealth) or the global smart
    # fragment setting. Global wins when set.
    frag = smart_fragment() or prof.get("fragment")
    if frag:
        _frag_spec = ",".join((frag["packets"], frag["length"],
                               frag["interval"]))
        params.append(f"fragment={_q(_frag_spec)}")
    frag = tag or _tag(user["username"], network.upper(), via)
    server = addr or host
    return f"vless://{user['uuid']}@{server}:443?{'&'.join(params)}#{_q(frag)}"


def vmess_uri(user: dict, host: str, path: str, via: str = "Direct",
              addr: str | None = None) -> str:
    path = f"{path}?ed=2560"
    cfg = {
        "v": "2",
        "ps": _tag(user["username"], "VMESS", via),
        "add": addr or host,
        "port": "443",
        "id": user["uuid"],
        "aid": "0",
        # aes-128-gcm: cheapest AEAD on phones, every modern ARM has AES HW
        "scy": "aes-128-gcm",
        "net": "ws",
        "type": "none",
        "host": host,
        "path": path,
        "tls": "tls",
        "sni": host,
        "alpn": "h2,http/1.1",
        "fp": "random",
    }
    blob = base64.b64encode(json.dumps(cfg, separators=(",", ":")).encode()).decode()
    return "vmess://" + blob


def trojan_uri(user: dict, host: str, path: str, via: str = "Direct",
               addr: str | None = None) -> str:
    path = f"{path}?ed=2560"
    params = [
        "security=tls",
        f"sni={host}",
        f"host={host}",
        "type=ws",
        f"path={_q(path)}",
        "fp=random",
        "alpn=h2,http%2F1.1",
    ]
    frag = _tag(user["username"], "TROJAN", via)
    server = addr or host
    return f"trojan://{_q(user['trojan_pass'])}@{server}:443?{'&'.join(params)}#{_q(frag)}"


# ── catalog ──────────────────────────────────────────────────────────────────

def host_list(host: str,
              cf_host: str | None = None,
              extra_hosts: list[str] | None = None) -> list[tuple[str, str]]:
    """Every hostname the configs should be generated for, as (host, label).

    Order: the primary hostname first ("Direct"), then manual/Railway
    alternates ("Alt"/"Railway"), then the Cloudflare Worker last ("CF").
    """
    seen: set[str] = set()
    out: list[tuple[str, str]] = []

    def push(h: str, label: str) -> None:
        h = (h or "").strip().lower()
        if not h or h in seen:
            return
        seen.add(h)
        out.append((h, label))

    push(host, "Direct")
    for h in (extra_hosts or []):
        if ".up.railway.app" in (h or ""):
            label = "Railway"
        elif "trycloudflare.com" in (h or "") or "cfargotunnel.com" in (h or ""):
            label = "Tunnel"
        else:
            label = "Alt"
        push(h, label)
    push(cf_host or "", "CF")
    return out


# ── pinned CDN IPs ("آیپی ثابت") ─────────────────────────────────────────────

def _is_public_ipv4(ip: str) -> bool:
    """True for a syntactically valid, globally routable IPv4 address."""
    parts = str(ip).strip().split(".")
    if len(parts) != 4 or not all(p.isdigit() for p in parts):
        return False
    a, b, c, d = (int(p) for p in parts)
    if any(x > 255 for x in (a, b, c, d)):
        return False
    if a in (0, 10, 127) or (a == 169 and b == 254):
        return False
    if a == 172 and 16 <= b <= 31:
        return False
    if a == 192 and b == 168:
        return False
    return True


def _ip_list(v) -> list[str]:
    """
    Normalise free-form input (panel textarea, env var, stored JSON) into a
    clean, unique, public-IPv4-only list. Junk is dropped silently so one
    bad line can never break every subscription.
    """
    if v is None:
        return []
    if isinstance(v, (list, tuple)):
        raw = ",".join(str(x) for x in v)
    else:
        raw = str(v)
    out: list[str] = []
    for part in raw.replace(";", ",").replace(" ", ",").split(","):
        p = part.strip()
        if p and _is_public_ipv4(p) and p not in out:
            out.append(p)
    return out


def normalize_ips(v) -> str:
    """The clean comma-separated form stored back into settings."""
    return ",".join(_ip_list(v)[:4])


def pinned_ips() -> list[str]:
    """The stored Pinned CDN IPs, sanitised. Empty when unset. Capped at 4."""
    return _ip_list(db.get_setting("cf_ips", ""))[:4]


# Transport kinds, used for the coarse selection and as the prefix of a
# selector id.
SELECTABLE_KINDS = ("httpupgrade", "xhttp", "ws", "trojan", "vmess",
                    "reality", "location")


def entry_id(entry: dict) -> str:
    """
    Stable identifier for one catalog entry, e.g.
        xhttp@Direct          the XHTTP config on the primary hostname
        ws@Railway            WebSocket on the *.up.railway.app name
        loc:us@Direct         the United States exit on the primary hostname
    """
    kind = entry.get("kind", "")
    if kind == "location":
        kind = "loc:" + (entry.get("country") or "")
    return f"{kind}@{entry.get('via', 'Direct')}"


def parse_kinds(raw: str | None) -> list[str]:
    """Normalise a stored allowed_kinds value."""
    if not raw:
        return []
    seen: list[str] = []
    for part in str(raw).replace(";", ",").split(","):
        k = part.strip()
        if not k:
            continue
        if "@" in k:
            kind, _, via = k.partition("@")
            k = f"{kind.strip().lower()}@{via.strip()}"
        else:
            k = k.lower()
        if k not in seen:
            seen.append(k)
    return seen


def entry_allowed(entry: dict, allowed: list[str]) -> bool:
    """True when this entry matches the user's selection."""
    if not allowed:
        return True
    if entry_id(entry) in allowed:
        return True
    kind = entry.get("kind", "")
    if kind in allowed:
        return True
    if kind == "location":
        if f"loc:{entry.get('country') or ''}" in allowed:
            return True
    return False


def filter_kinds(entries: list[dict], allowed: list[str]) -> list[dict]:
    """Keep only the transports a user is allowed to receive."""
    if not allowed:
        return entries
    kept = [c for c in entries if entry_allowed(c, allowed)]
    return kept or entries


def catalog(user: dict, host: str,
            cf_host: str | None = None,
            profile: str | None = None,
            extra_hosts: list[str] | None = None,
            lang: str = "en") -> list[dict]:
    """Every config we can hand out, ordered best-first."""
    prof = profiles.get(profile)
    out: list[dict] = []

    def add(kind, label, badge, uri, path, via, featured=False, note="",
            country=""):
        e = {
            "kind": kind, "label": label, "badge": badge, "uri": uri,
            "path": path, "via": via, "featured": featured, "note": note,
        }
        if country:
            e["country"] = country
        e["id"] = entry_id(e)
        out.append(e)

    hosts = host_list(host, cf_host, extra_hosts)

    for h, via in hosts:
        add("xhttp", f"VLESS + XHTTP ({via})", "b-xhttp",
            vless_uri(user, h, "xhttp", paths.P_XHTTP, via, prof),
            paths.P_XHTTP, via,
            note="Best for downloads and streaming · survives strict CDNs")
        add("httpupgrade", f"VLESS + HTTPUpgrade ({via})", "b-vless",
            vless_uri(user, h, "httpupgrade", paths.P_UPGRADE, via, prof),
            paths.P_UPGRADE, via, featured=(via == "Direct"),
            note="⭐ LOWEST PING · use this for games")
        add("ws", f"VLESS + WebSocket ({via})", "b-vless",
            vless_uri(user, h, "ws", paths.P_VLESS, via, prof),
            paths.P_VLESS, via,
            note="Same latency as HTTPUpgrade · widest client support")
        add("trojan", f"Trojan + WS ({via})", "b-trojan",
            trojan_uri(user, h, paths.P_TROJAN, via),
            paths.P_TROJAN, via)
        add("vmess", f"VMess + WS ({via})", "b-vmess",
            vmess_uri(user, h, paths.P_VMESS, via),
            paths.P_VMESS, via)

    # ── pinned CDN IP entries ("Fixed IP") ────────────────────────────
    # Dial a fixed CDN IP while SNI/Host stay the hostname: the standard
    # workaround when an ISP blocks the hostname's DNS/SNI but the CDN
    # still routes by SNI. Two transports per IP (HTTPUpgrade + WS).
    if hosts:
        _h0 = hosts[0][0]
        for i, ip in enumerate(pinned_ips(), 1):
            _via = f"IP{i}"
            add("httpupgrade", f"VLESS + HTTPUpgrade ({_via})", "b-vless",
                vless_uri(user, _h0, "httpupgrade", paths.P_UPGRADE,
                          _via, prof, addr=ip),
                paths.P_UPGRADE, _via,
                note=f"⚡{_via} Fixed IP · dials {ip}, SNI/Host stay {_h0}")
            add("ws", f"VLESS + WebSocket ({_via})", "b-vless",
                vless_uri(user, _h0, "ws", paths.P_VLESS, _via, prof,
                          addr=ip),
                paths.P_VLESS, _via,
                note=f"⚡{_via} Fixed IP · dials {ip}, SNI/Host stay {_h0}")

    # ── REALITY (raw TCP, strongest anti-DPI) ───────────────────────────
    try:
        if reality.enabled():
            r_uri = reality.share_link(user, host)
            if r_uri:
                # REALITY is one config per user; host is the REALITY public host
                rh = (reality.reality_host() or host).strip()
                add("reality", f"VLESS + REALITY ({rh})", "b-reality",
                    r_uri, "tcp:reality", "Direct", featured=True,
                    note=f"🔒 REALITY · dest {reality.dest()} · mimics {reality.server_name()} · strongest bypass")
    except Exception:
        pass

    # ── country exits ─────────────────────────────────────────────────
    for _code in locations.verified_codes():
        _flag = locations.flag(_code)
        _name = (locations.label_fa(_code) if lang == "fa"
                 else locations.label(_code))
        for h, via in hosts:
            add("location", f"{_flag} {_name} ({via})", "b-loc",
                vless_uri(user, h, "ws", locations.path_for(_code),
                          via, prof, tag=f"{_flag}{_name}-{via}"),
                locations.path_for(_code), via,
                note=f"🌍 Exits in {_name} · via Tor, so expect 500ms+ · "
                     f"NOT for gaming",
                country=_code)

    # reorder by the profile's preferred transport
    pref = prof.get("prefer", "xhttp")
    out.sort(key=lambda c: (c["kind"] == "location",
                            c["via"] != "Direct", c["kind"] != pref))

    # Per-user transport selection.
    return filter_kinds(out, parse_kinds(user.get("allowed_kinds")))


# ── subscription info line ───────────────────────────────────────────────────

def _fmt_bytes(n: int) -> str:
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unit == "TB":
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.2f}{unit}"
        n /= 1024
    return f"{n:.2f}TB"


def info_entries(user: dict, host: str) -> list[dict]:
    """
    Non-functional entries that carry quota and expiry into the client's
    server list.
    """
    import time as _t
    used = int(user.get("used_up", 0)) + int(user.get("used_down", 0))
    quota = int(user.get("quota_bytes", 0) or 0)
    expires = int(user.get("expires_at", 0) or 0)

    if quota:
        left = max(0, quota - used)
        pct = min(100, round(used / quota * 100)) if quota else 0
        traffic = (f"📊 {_fmt_bytes(used)} / {_fmt_bytes(quota)}"
                   f"  ({pct}%)  ·  {_fmt_bytes(left)} left")
    else:
        traffic = f"📊 {_fmt_bytes(used)} used  ·  unlimited"

    if expires:
        days = int((expires - _t.time()) // 86400)
        stamp = _t.strftime("%Y-%m-%d", _t.localtime(expires))
        if days < 0:
            when = f"⛔ EXPIRED  ·  {stamp}"
        elif days == 0:
            when = f"⏳ expires TODAY  ·  {stamp}"
        else:
            when = f"⏳ {days} days left  ·  {stamp}"
    else:
        when = "⏳ never expires"

    out = []
    for text in (traffic, when):
        out.append({
            "kind": "info", "label": text, "badge": "b-info",
            "uri": (f"vless://00000000-0000-0000-0000-000000000000"
                    f"@127.0.0.1:1?encryption=none&security=none"
                    f"&type=tcp#{_q(text)}"),
            "path": "", "via": "Info", "featured": False, "note": text,
            "info": True,
        })
    return out


# ── subscription formats ─────────────────────────────────────────────────────

def sub_raw(user: dict, host: str,
            cf_host: str | None = None,
            profile: str | None = None,
            extra_hosts: list[str] | None = None,
            with_info: bool = True) -> str:
    entries = catalog(user, host, cf_host, profile, extra_hosts)
    if with_info:
        entries = info_entries(user, host) + entries
    return "\n".join(c["uri"] for c in entries)


def sub_base64(user: dict, host: str,
               cf_host: str | None = None,
               profile: str | None = None,
               extra_hosts: list[str] | None = None,
               with_info: bool = True) -> str:
    return base64.b64encode(
        sub_raw(user, host, cf_host, profile, extra_hosts,
                with_info).encode()).decode()


def sub_clash(user: dict, host: str,
              cf_host: str | None = None,
              profile: str | None = None,
              extra_hosts: list[str] | None = None) -> str:
    prof = profiles.get(profile)
    proxies, names = [], []
    hosts = host_list(host, cf_host, extra_hosts)
    allowed = parse_kinds(user.get("allowed_kinds"))

    def want(kind: str, via: str = "", country: str = "") -> bool:
        return entry_allowed(
            {"kind": kind, "via": via, "country": country}, allowed)

    for h, via in hosts:
        base_ws = {
            "server": h, "port": 443, "udp": True, "tls": True,
            "servername": h, "skip-cert-verify": False,
            "client-fingerprint": "random",
            "alpn": ["h2", "http/1.1"],
        }
        if want("httpupgrade", via):
            n = _tag(user["username"], "HU", via)
            proxies.append({**base_ws, "name": n, "type": "vless",
                            "uuid": user["uuid"], "network": "httpupgrade",
                            "ws-opts": {"path": paths.P_UPGRADE,
                                        "headers": {"Host": h}}})
            names.append(n)

        if want("ws", via):
            n = _tag(user["username"], "WS", via)
            proxies.append({**base_ws, "name": n, "type": "vless",
                            "uuid": user["uuid"], "network": "ws",
                            "ws-opts": {"path": paths.P_VLESS,
                                        "headers": {"Host": h}}})
            names.append(n)

        if want("trojan", via):
            n = _tag(user["username"], "TROJAN", via)
            proxies.append({**base_ws, "name": n, "type": "trojan",
                            "password": user["trojan_pass"], "network": "ws",
                            "sni": h,
                            "ws-opts": {"path": paths.P_TROJAN,
                                        "headers": {"Host": h}}})
            names.append(n)

        if want("vmess", via):
            n = _tag(user["username"], "VMESS", via)
            proxies.append({**base_ws, "name": n, "type": "vmess",
                            "uuid": user["uuid"], "alterId": 0,
                            "cipher": "auto", "network": "ws",
                            "ws-opts": {"path": paths.P_VMESS,
                                        "headers": {"Host": h}}})
            names.append(n)

        for _code in locations.verified_codes():
            if want("location", via, _code):
                n = f"{locations.flag(_code)}{locations.label(_code)}-{via}"
                proxies.append({**base_ws, "name": n, "type": "vless",
                                "uuid": user["uuid"],
                                "network": "ws",
                                "ws-opts": {
                                    "path": locations.path_for(_code),
                                    "headers": {"Host": h}}})
                names.append(n)

        # REALITY (Clash Meta supports reality-opts)
        try:
            if want("reality", via) and reality.enabled():
                # REALITY in Clash: server is the REALITY host, port is REALITY_PORT
                rh = (reality.reality_host() or h).strip() or h
                rp = reality.reality_port()
                n = _tag(user["username"], "REALITY", via)
                proxies.append({
                    "name": n, "type": "vless", "server": rh, "port": rp,
                    "udp": True, "tls": True, "servername": reality.server_name(),
                    "client-fingerprint": reality.fingerprint() if reality.fingerprint() != "random" else "chrome",
                    "reality-opts": {
                        "public-key": reality.public_key(),
                        "short-id": reality.short_id(),
                    },
                    "uuid": user["uuid"], "flow": "xtls-rprx-vision",
                    "network": "tcp",
                })
                names.append(n)
        except Exception:
            pass

    # ── pinned CDN IPs: dial the IP, keep the hostname as SNI ─────────
    if hosts:
        _h0 = hosts[0][0]
        for i, ip in enumerate(pinned_ips(), 1):
            _via = f"IP{i}"
            if want("httpupgrade", _via):
                n = _tag(user["username"], "HU", _via)
                proxies.append({
                    "name": n, "type": "vless", "server": ip, "port": 443,
                    "udp": True, "tls": True, "servername": _h0,
                    "skip-cert-verify": False,
                    "client-fingerprint": "random",
                    "alpn": ["h2", "http/1.1"],
                    "uuid": user["uuid"], "network": "httpupgrade",
                    "ws-opts": {"path": paths.P_UPGRADE,
                                "headers": {"Host": _h0}}})
                names.append(n)
            if want("ws", _via):
                n = _tag(user["username"], "WS", _via)
                proxies.append({
                    "name": n, "type": "vless", "server": ip, "port": 443,
                    "udp": True, "tls": True, "servername": _h0,
                    "skip-cert-verify": False,
                    "client-fingerprint": "random",
                    "alpn": ["h2", "http/1.1"],
                    "uuid": user["uuid"], "network": "ws",
                    "ws-opts": {"path": paths.P_VLESS,
                                "headers": {"Host": _h0}}})
                names.append(n)

    doc = {
        "mixed-port": 7890,
        "allow-lan": False,
        "mode": "rule",
        "log-level": "warning",
        "proxies": proxies,
        "proxy-groups": [
            {"name": "🎮 AUTO", "type": "url-test", "proxies": names,
             "url": "http://www.gstatic.com/generate_204",
             "interval": 120, "tolerance": 40},
            {"name": "🚀 ULTRA", "type": "select",
             "proxies": ["🎮 AUTO"] + names},
        ],
        "rules": [
            "GEOIP,private,DIRECT,no-resolve",
            "MATCH,🚀 ULTRA",
        ],
    }
    return _yaml(doc)


def sub_singbox(user: dict, host: str,
                cf_host: str | None = None,
                profile: str | None = None,
                extra_hosts: list[str] | None = None) -> str:
    prof = profiles.get(profile)
    outs, names = [], []
    hosts = host_list(host, cf_host, extra_hosts)
    allowed = parse_kinds(user.get("allowed_kinds"))

    def want(kind: str, via: str = "", country: str = "") -> bool:
        return entry_allowed(
            {"kind": kind, "via": via, "country": country}, allowed)

    def tls(h):
        return {"enabled": True, "server_name": h, "insecure": False,
                "alpn": ["h2", "http/1.1"],
                "utls": {"enabled": True, "fingerprint": "random"}}

    def mux():
        m = prof.get("mux") or {}
        conc = int(m.get("concurrency", 8))
        if not m.get("enabled") or conc <= 0:
            return {"enabled": False}
        return {"enabled": True, "protocol": "h2mux",
                "max_streams": conc, "padding": True}

    for h, via in hosts:
        if want("httpupgrade", via):
            n = _tag(user["username"], "HU", via)
            outs.append({
                "type": "vless", "tag": n, "server": h, "server_port": 443,
                "uuid": user["uuid"], "tls": tls(h), "multiplex": mux(),
                "packet_encoding": "xudp",
                "transport": {"type": "httpupgrade",
                              "path": paths.P_UPGRADE, "host": h},
            })
            names.append(n)

        if want("ws", via):
            n = _tag(user["username"], "WS", via)
            outs.append({
                "type": "vless", "tag": n, "server": h, "server_port": 443,
                "uuid": user["uuid"], "tls": tls(h), "multiplex": mux(),
                "packet_encoding": "xudp",
                "transport": {
                    "type": "ws", "path": paths.P_VLESS,
                    "headers": {"Host": h},
                    "max_early_data": 2560,
                    "early_data_header_name": "Sec-WebSocket-Protocol"},
            })
            names.append(n)

        if want("trojan", via):
            n = _tag(user["username"], "TROJAN", via)
            outs.append({
                "type": "trojan", "tag": n, "server": h, "server_port": 443,
                "password": user["trojan_pass"], "tls": tls(h),
                "transport": {"type": "ws", "path": paths.P_TROJAN,
                              "headers": {"Host": h}},
            })
            names.append(n)

        for _code in locations.verified_codes():
            if want("location", via, _code):
                n = f"{locations.flag(_code)}{locations.label(_code)}-{via}"
                outs.append({
                    "type": "vless", "tag": n, "server": h,
                    "server_port": 443, "uuid": user["uuid"],
                    "tls": tls(h), "multiplex": mux(),
                    "packet_encoding": "xudp",
                    "transport": {"type": "ws",
                                  "path": locations.path_for(_code),
                                  "headers": {"Host": h},
                                  "max_early_data": 2560,
                                  "early_data_header_name":
                                      "Sec-WebSocket-Protocol"},
                })
                names.append(n)

        # REALITY for sing-box (1.8+)
        try:
            if want("reality", via) and reality.enabled():
                rh = (reality.reality_host() or h).strip() or h
                rp = reality.reality_port()
                n = _tag(user["username"], "REALITY", via)
                outs.append({
                    "type": "vless", "tag": n, "server": rh, "server_port": rp,
                    "uuid": user["uuid"],
                    "flow": "xtls-rprx-vision",
                    "tls": {
                        "enabled": True, "server_name": reality.server_name(),
                        "insecure": False,
                        "utls": {"enabled": True, "fingerprint": reality.fingerprint() if reality.fingerprint() != "random" else "chrome"},
                        "reality": {
                            "enabled": True,
                            "public_key": reality.public_key(),
                            "short_id": reality.short_id(),
                        },
                    },
                    "multiplex": mux(),
                    "packet_encoding": "xudp",
                })
                names.append(n)
        except Exception:
            pass

    # ── pinned CDN IPs ────────────────────────────────────────────────
    if hosts:
        h0 = hosts[0][0]
        for i, ip in enumerate(pinned_ips(), 1):
            via = f"IP{i}"
            if want("httpupgrade", via):
                n = _tag(user["username"], "HU", via)
                outs.append({
                    "type": "vless", "tag": n, "server": ip,
                    "server_port": 443, "uuid": user["uuid"],
                    "tls": tls(h0), "multiplex": mux(),
                    "packet_encoding": "xudp",
                    "transport": {"type": "httpupgrade",
                                  "path": paths.P_UPGRADE, "host": h0},
                })
                names.append(n)
            if want("ws", via):
                n = _tag(user["username"], "WS", via)
                outs.append({
                    "type": "vless", "tag": n, "server": ip,
                    "server_port": 443, "uuid": user["uuid"],
                    "tls": tls(h0), "multiplex": mux(),
                    "packet_encoding": "xudp",
                    "transport": {"type": "ws", "path": paths.P_VLESS,
                                  "headers": {"Host": h0},
                                  "max_early_data": 2560,
                                  "early_data_header_name":
                                      "Sec-WebSocket-Protocol"},
                })
                names.append(n)

    doc = {
        "log": {"level": "warn", "timestamp": True},
        "dns": {
            "servers": [
                {"tag": "remote", "address": "https://1.1.1.1/dns-query",
                 "detour": "🎮 AUTO"},
                {"tag": "local", "address": "local", "detour": "direct"},
            ],
            "rules": [{"outbound": "any", "server": "local"}],
            "strategy": "ipv4_only",
        },
        "inbounds": [{
            "type": "tun", "tag": "tun-in", "address": ["172.19.0.1/30"],
            "auto_route": True, "strict_route": True, "stack": "mixed",
            "sniff": True,
        }],
        "outbounds": outs + [
            {"type": "urltest", "tag": "🎮 AUTO", "outbounds": names,
             "url": "http://www.gstatic.com/generate_204",
             "interval": "2m", "tolerance": 40, "idle_timeout": "10m"},
            {"type": "selector", "tag": "🚀 ULTRA",
             "outbounds": ["🎮 AUTO"] + names, "default": "🎮 AUTO"},
            {"type": "direct", "tag": "direct"},
            {"type": "block", "tag": "block"},
        ],
        "route": {
            "auto_detect_interface": True,
            "final": "🚀 ULTRA",
            "rules": [
                {"action": "sniff"},
                {"ip_is_private": True, "outbound": "direct"},
            ],
        },
        "experimental": {
            "cache_file": {"enabled": True, "store_fakeip": False},
        },
    }
    return json.dumps(doc, indent=2, ensure_ascii=False)


# ── tiny YAML emitter (no PyYAML dependency) ─────────────────────────────────

def _yaml(obj, indent: int = 0) -> str:
    sp = "  " * indent
    if isinstance(obj, dict):
        lines = []
        for k, v in obj.items():
            if isinstance(v, (dict, list)) and v:
                lines.append(f"{sp}{_yk(k)}:")
                lines.append(_yaml(v, indent + 1))
            else:
                lines.append(f"{sp}{_yk(k)}: {_yv(v)}")
        return "\n".join(lines)
    if isinstance(obj, list):
        lines = []
        for item in obj:
            if isinstance(item, (dict, list)) and item:
                body = _yaml(item, indent + 1)
                first, *rest = body.split("\n")
                lines.append(f"{sp}- {first.strip()}")
                lines.extend(rest)
            else:
                lines.append(f"{sp}- {_yv(item)}")
        return "\n".join(lines)
    return f"{sp}{_yv(obj)}"


def _yk(k) -> str:
    s = str(k)
    return f'"{s}"' if any(c in s for c in ": #{}[]&*!|>'\"%@`") else s


def _yv(v) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    s = str(v)
    if s == "" or any(c in s for c in ": #{}[]&*!|>'\"%@`,") or s.strip() != s:
        return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return s
