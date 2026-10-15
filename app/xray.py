"""
ULTRA GAMING VPN — Xray control plane

Responsibilities
----------------
* Render /etc/xray/config.json from the user DB + runtime settings
* Start / stop / reload the xray process (graceful, atomic)
* Query per-user traffic counters via the Xray gRPC StatsService
  (through the `xray api statsquery` CLI so we need no protobuf deps)

Notes
-----
Railway terminates TLS for us and only forwards TCP/HTTP on $PORT,
therefore the default inbounds live behind nginx. REALITY (when enabled)
listens directly on REALITY_PORT (raw TCP, outside nginx) — see app/reality.py.
UDP protocols (Hysteria2/TUIC) are not offered — Railway does not route UDP.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import tempfile
import threading
import time

from . import db, locations, paths, reality

XRAY_BIN = os.environ.get("XRAY_BIN", "/usr/local/bin/xray")
CONFIG_PATH = os.environ.get("XRAY_CONFIG", "/etc/xray/config.json")
API_ADDR = "127.0.0.1:10085"

# inbound tag -> (port, path)
INBOUNDS = {
    "vless-xhttp": (7004, paths.P_XHTTP),
    "vless-ws": (7001, paths.P_VLESS),
    "vless-hu": (7005, paths.P_UPGRADE),
    "vmess-ws": (7002, paths.P_VMESS),
    "trojan-ws": (7003, paths.P_TROJAN),
}

_proc: subprocess.Popen | None = None
_lock = threading.Lock()


# ── config rendering ─────────────────────────────────────────────────────────

def _policy(turbo: bool) -> dict:
    """
    Traffic policy.

    Level 0 = normal users, level 1 = boosted users (idea #7).

    THROUGHPUT-FIRST by default (this build was asked to move data as fast
    as possible and to not care about system resources): normal traffic is
    buffered (4 MB per connection) so bulk transfers fill the pipe. Turbo
    mode and per-user Boost switch the same level back to zero-buffer for
    minimum latency — that escape hatch stays for competitive play.

    connIdle is deliberately generous: games keep TCP sessions open with long
    silent gaps, and a short idle timeout is the usual cause of "it randomly
    disconnects". uplinkOnly/downlinkOnly are set to 0 so that a half-closed
    connection is never torn down while the other direction is still live —
    that is the other classic disconnect source.
    """
    if turbo:
        base = {
            "handshake": 3,
            "connIdle": 600,
            "uplinkOnly": 0,
            "downlinkOnly": 0,
            "bufferSize": 0,          # 0 = no buffering -> lowest latency
        }
    else:
        base = {
            "handshake": 3,
            "connIdle": 600,
            "uplinkOnly": 0,
            "downlinkOnly": 0,
            "bufferSize": 4,
        }
    stats = {"statsUserUplink": True, "statsUserDownlink": True}

    lvl0 = {**base, **stats}
    # Boosted level: always zero-buffer, fastest handshake, longest patience.
    lvl1 = {**base, **stats, "handshake": 2, "bufferSize": 0, "connIdle": 900}

    return {
        "levels": {"0": lvl0, "1": lvl1},
        "system": {
            "statsInboundUplink": True,
            "statsInboundDownlink": True,
            "statsOutboundUplink": True,
            "statsOutboundDownlink": True,
        },
    }


def _inbound_sockopt() -> dict:
    """Keepalive for the nginx→Xray loopback connections.

    These sockets only face nginx over loopback, but a keepalive probe
    still detects a wedged peer faster than the OS default (hours), which
    turns rare stuck tunnels into quick reconnects.
    """
    return {"tcpKeepAliveIdle": 30, "tcpKeepAliveInterval": 15}


def _sniffing() -> dict:
    """
    Sniffing is DISABLED on purpose.

    With destOverride and routeOnly=false the server rewrites each
    connection's destination to whatever hostname it sniffed out of the
    payload, then re-resolves that name with its own DNS. For a game that
    means:

      * every connection pays an extra server-side DNS lookup (latency)
      * the game's own IP choice is thrown away and replaced by whatever
        the server's resolver returns — often a different edge node, so
        matchmaking and voice servers become unreachable
      * QUIC sniffing mangles UDP-over-TCP sessions, which is why titles
        that use QUIC simply fail to load

    We route everything direct anyway, so there is nothing to sniff for.
    Leaving it off keeps the client's original destination intact, which
    is exactly what games need.
    """
    return {"enabled": False}


def build_config(users: list[dict] | None = None,
                 turbo: bool | None = None) -> dict:
    if users is None:
        users = db.active_users()
    if turbo is None:
        turbo = bool(db.get_setting("turbo_mode", False))

    # Boosted users are placed on policy level 1 (zero-buffer, fast handshake)
    try:
        boosted = set(db.boosts_active())
    except Exception:
        boosted = set()

    def _lvl(u: dict) -> int:
        return 1 if u["id"] in boosted else 0

    vless_clients = [{"id": u["uuid"], "email": _email(u), "level": _lvl(u)}
                     for u in users]
    vmess_clients = [{"id": u["uuid"], "email": _email(u), "alterId": 0,
                      "level": _lvl(u)} for u in users]
    trojan_clients = [{"password": u["trojan_pass"], "email": _email(u),
                       "level": _lvl(u)} for u in users]
    inbounds = [
        {
            "tag": "vless-xhttp",
            "port": INBOUNDS["vless-xhttp"][0],
            "listen": "127.0.0.1",
            "protocol": "vless",
            "settings": {"clients": vless_clients, "decryption": "none"},
            "streamSettings": {
                "network": "xhttp",
                "sockopt": _inbound_sockopt(),
                # XHTTP packet-up mode: uploads are individual HTTP POSTs,
                # downloads are one long streamed GET. nginx proxies each
                # POST to the Xray inbound via the xray_xhttp upstream
                # (keepalive 64). The key tuning knobs:
                #
                # scMinPostsIntervalMs: minimum gap between POST requests.
                # The default 30ms is too conservative for gaming — each
                # upload chunk is a game packet batch, and waiting 30ms
                # adds that latency to every upload. Lower to 4ms for
                # responsive gameplay; the nginx keepalive pool handles
                # the request rate without TCP churn.
                #
                # scMaxEachPostBytes: how much payload per POST. Bigger
                # = fewer requests per second = less overhead. A 200-500KB
                # range lets the client batch game packets efficiently
                # while keeping individual request latency low.
                #
                # scMaxBufferedPosts: how many POSTs Xray will accept
                # without a response. 32 is enough for bursty game traffic
                # without unbounded memory growth.
                #
                # xPaddingBytes: minimal padding. Too much padding wastes
                # bandwidth on small game packets. 10-50 bytes is enough
                # for anti-fingerprinting without measurable overhead.
                "xhttpSettings": {
                    "path": paths.P_XHTTP,
                    "mode": "packet-up",
                    "scMaxEachPostBytes": "200000-500000",
                    "scMinPostsIntervalMs": "1-3",
                    "scMaxBufferedPosts": 64,
                    "xPaddingBytes": "10-50",
                },
            },
            "sniffing": _sniffing(),
        },
        {
            "tag": "vless-ws",
            "port": INBOUNDS["vless-ws"][0],
            "listen": "127.0.0.1",
            "protocol": "vless",
            "settings": {"clients": vless_clients, "decryption": "none"},
            "streamSettings": {
                "network": "ws",
                "sockopt": _inbound_sockopt(),
                "wsSettings": {"path": paths.P_VLESS,
                               "heartbeatPeriod": 20},
            },
            "sniffing": _sniffing(),
        },
        {
            "tag": "vless-hu",
            "port": INBOUNDS["vless-hu"][0],
            "listen": "127.0.0.1",
            "protocol": "vless",
            "settings": {"clients": vless_clients, "decryption": "none"},
            "streamSettings": {
                "network": "httpupgrade",
                "sockopt": _inbound_sockopt(),
                "httpupgradeSettings": {"path": paths.P_UPGRADE},
            },
            "sniffing": _sniffing(),
        },
        {
            "tag": "vmess-ws",
            "port": INBOUNDS["vmess-ws"][0],
            "listen": "127.0.0.1",
            "protocol": "vmess",
            "settings": {"clients": vmess_clients},
            "streamSettings": {
                "network": "ws",
                "sockopt": _inbound_sockopt(),
                "wsSettings": {"path": paths.P_VMESS,
                               "heartbeatPeriod": 20},
            },
            "sniffing": _sniffing(),
        },
        {
            "tag": "trojan-ws",
            "port": INBOUNDS["trojan-ws"][0],
            "listen": "127.0.0.1",
            "protocol": "trojan",
            "settings": {"clients": trojan_clients},
            "streamSettings": {
                "network": "ws",
                "sockopt": _inbound_sockopt(),
                "wsSettings": {"path": paths.P_TROJAN,
                               "heartbeatPeriod": 20},
            },
            "sniffing": _sniffing(),
        },
    ]

    # ── country-exit inbounds (see app/locations.py) ──────────────────
    for _code in locations.verified_codes():
        _port = locations.ports(_code)[2]
        inbounds.append({
            "tag": locations.inbound_tag(_code),
            "port": _port,
            "listen": "127.0.0.1",
            "protocol": "vless",
            "settings": {"clients": vless_clients, "decryption": "none"},
            "streamSettings": {
                "network": "ws",
                "wsSettings": {"path": locations.path_for(_code),
                               "heartbeatPeriod": 20},
                "sockopt": {
                    "tcpKeepAliveIdle": 30,
                    "tcpKeepAliveInterval": 15,
                },
            },
            "sniffing": _sniffing(),
        })

    # REALITY inbound (raw TCP, outside nginx) — only when enabled
    try:
        r_in = reality.inbound_config(vless_clients)
        if r_in:
            inbounds.append(r_in)
    except Exception:
        pass

    inbounds += [
        {
            "tag": "api",
            "port": 10085,
            "listen": "127.0.0.1",
            "protocol": "dokodemo-door",
            "settings": {"address": "127.0.0.1"},
            "streamSettings": {"network": "tcp"},
        },
    ]

    return {
        "log": {"loglevel": os.environ.get("XRAY_LOGLEVEL", "warning")},
        "stats": {},
        "api": {"tag": "api", "services": ["StatsService", "HandlerService"]},
        "policy": _policy(turbo),
        # Cached IPv4-only resolution. Railway has no usable IPv6 egress, so
        # asking for AAAA records only adds a timeout to every first lookup.
        # localhost first = the container's own resolver answers instantly for
        # anything already cached by the platform.
        "dns": {
            "servers": ["localhost", "1.1.1.1", "1.0.0.1", "8.8.8.8"],
            "queryStrategy": "UseIPv4",
            "disableCache": False,
            "disableFallbackIfMatch": False,
            "tag": "dns-out",
        },
        "inbounds": inbounds,
        "outbounds": [
            {
                "tag": "direct",
                "protocol": "freedom",
                # UseIPv4 avoids the IPv6 lookup stall that shows up as a
                # 1-2s hitch on the first connection to each game host.
                "settings": {"domainStrategy": "UseIPv4"},
                "streamSettings": {
                    "sockopt": {
                        # Nagle off: small game packets leave immediately
                        # instead of waiting to be coalesced.
                        "tcpNoDelay": True,
                        # Send the first data segment together with the
                        # handshake instead of waiting a full round trip.
                        "tcpFastOpen": True,
                        # Probe idle sockets so a dead path is detected in
                        # seconds instead of hanging on the OS default (~2h).
                        "tcpKeepAliveIdle": 30,
                        "tcpKeepAliveInterval": 15,
                        # Give up on an unacknowledged segment after 10s so
                        # a stalled route fails fast and the client reconnects,
                        # instead of the session appearing frozen.
                        "tcpUserTimeout": 10000,
                        # BBR reaches full throughput far quicker than cubic
                        # on lossy mobile links.
                        "tcpcongestion": "bbr",
                        # Stay under the common 1500-byte MTU (minus tunnel
                        # overhead) so packets are never fragmented mid-path.
                        "tcpMaxSeg": 1400,
                    }
                },
            },
            {"tag": "blocked", "protocol": "blackhole",
             "settings": {"response": {"type": "http"}}},
            # One SOCKS outbound per verified location, pointing at that
            # country's local Tor instance. The sockopt block mirrors the
            # direct outbound: Tor adds enough latency on its own, so the
            # loopback leg to it must never add more (Nagle, stalls, or
            # fragmented packets).
            *[{
                "tag": locations.inbound_tag(c),
                "protocol": "socks",
                "settings": {"servers": [{
                    "address": "127.0.0.1",
                    "port": locations.ports(c)[0],
                }]},
                "streamSettings": {"sockopt": {
                    "tcpNoDelay": True,
                    "tcpFastOpen": True,
                    "tcpKeepAliveIdle": 30,
                    "tcpKeepAliveInterval": 15,
                    "tcpUserTimeout": 10000,
                    "tcpMaxSeg": 1400,
                }},
            } for c in locations.verified_codes()],
        ],
        # AsIs skips the pre-routing DNS lookup that IPIfNonMatch performs on
        # every single connection. Since everything is routed direct anyway,
        # resolving twice only added latency to each new game connection.
        "routing": {
            "domainStrategy": "AsIs",
            "rules": [
                {"type": "field", "inboundTag": ["api"], "outboundTag": "api"},
                {"type": "field", "protocol": ["bittorrent"],
                 "outboundTag": "blocked"},
                # never let the tunnel reach private networks: our own
                # control plane, or Railway's internal 172.x mesh. A
                # leaked request into RFC1918 would be a security hole.
                {"type": "field",
                 "ip": ["127.0.0.1/32", "::1/128", "169.254.0.0/16",
                        "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
                        "fc00::/7"],
                 "outboundTag": "blocked"},
                # Bind each location inbound to its own country outbound.
                *[{
                    "type": "field",
                    "inboundTag": [locations.inbound_tag(c)],
                    "outboundTag": locations.inbound_tag(c),
                } for c in locations.verified_codes()],
                {"type": "field", "outboundTag": "direct",
                 "network": "tcp,udp"},
            ],
        },
    }


def _email(u: dict) -> str:
    """Stats key. Must be stable and unique per user."""
    return f"{u['id']}.{u['username']}"


def ss_key(secret: str) -> str:
    """Shadowsocks-2022 aes-128-gcm needs a 16-byte base64 PSK."""
    import base64
    import hashlib
    return base64.b64encode(hashlib.sha256(secret.encode()).digest()[:16]).decode()


def server_ss_key() -> str:
    """The inbound-level PSK. Clients need it as the first half of their
    'serverPSK:userPSK' password."""
    return ss_key(os.environ.get("SS_MASTER", "ultra-gaming"))


def write_config(cfg: dict | None = None) -> dict:
    cfg = cfg or build_config()
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(CONFIG_PATH), suffix=".json")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(cfg, f, indent=2)
        os.replace(tmp, CONFIG_PATH)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return cfg


def validate(cfg_path: str = CONFIG_PATH) -> tuple[bool, str]:
    if not shutil.which(XRAY_BIN) and not os.path.exists(XRAY_BIN):
        return True, "xray binary not present (skipped validation)"
    try:
        r = subprocess.run([XRAY_BIN, "run", "-test", "-config", cfg_path],
                           capture_output=True, text=True, timeout=20)
        return r.returncode == 0, (r.stdout + r.stderr).strip()
    except Exception as e:  # pragma: no cover
        return False, str(e)


# ── process management ───────────────────────────────────────────────────────

def available() -> bool:
    return os.path.exists(XRAY_BIN) or bool(shutil.which(XRAY_BIN))


def start() -> bool:
    """Best-effort start. Never raises — the panel must survive a broken xray."""
    global _proc
    with _lock:
        if _proc and _proc.poll() is None:
            return True
        try:
            write_config()
        except Exception as e:
            db.log_event(f"Cannot write xray config: {e}",
                         kind="xray", level="error")
            return False
        if not available():
            db.log_event("Xray binary not found; running control-plane only",
                         kind="xray", level="warn")
            return False
        ok, msg = validate()
        if not ok:
            db.log_event(f"Xray config invalid: {msg[:400]}",
                         kind="xray", level="error")
            return False
        try:
            _proc = subprocess.Popen(
                [XRAY_BIN, "run", "-config", CONFIG_PATH],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except Exception as e:
            db.log_event(f"Cannot spawn xray: {e}", kind="xray", level="error")
            _proc = None
            return False
        time.sleep(1.0)
        alive = _proc.poll() is None
        db.log_event("Xray started" if alive else "Xray failed to start",
                     kind="xray", level="info" if alive else "error")
        return alive


def is_alive() -> bool:
    return bool(_proc and _proc.poll() is None)


_watch_last = 0.0
_watch_since: float | None = None


def ensure_alive(grace: float = 45, cooldown: float = 300) -> bool:
    """
    Watchdog: bring Xray back if it died.

    Called every few seconds by the metrics loop; cheap when everything is
    fine (one poll() on a live process). When Xray is down it waits GRACE
    seconds before acting (the panel must stay up and keep serving so a
    flapping process is visible, not hidden), then restarts at most once per
    COOLDOWN so a config that makes Xray crash on boot cannot create a
    restart loop.
    """
    global _watch_last, _watch_since
    if is_alive():
        _watch_since = None
        return True
    if not available():
        return False
    now = time.time()
    if _watch_since is None:
        _watch_since = now
        return False
    if now - _watch_since < grace:
        return False
    if now - _watch_last < cooldown:
        return False
    _watch_last = now
    db.log_event("Xray is down — attempting auto-restart", kind="xray",
                 level="warn")
    ok = start()
    db.log_event("Xray auto-restart " + ("succeeded" if ok else "failed"),
                 kind="xray", level="info" if ok else "error")
    return ok


def stop() -> None:
    global _proc
    with _lock:
        if _proc and _proc.poll() is None:
            _proc.send_signal(signal.SIGTERM)
            try:
                _proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                _proc.kill()
        _proc = None


# ── coalesced reload ─────────────────────────────────────────────────────────
#
# Every admin mutation (create/edit/delete/reset/boost/trial) used to restart
# Xray immediately. Xray has no hot reload, so a burst of edits — importing a
# list of players, editing quotas one by one — restarted the process once per
# click and every live tunnel in between paid a reconnect.
#
# The window only engages after a SUCCESSFUL reload: when the binary is
# missing or the config is broken every call must keep attempting (and keep
# reporting the failure) so the panel never shows a stale "applied".

_RELOAD_LOCK = threading.Lock()
_RELOAD_WINDOW = 2.0            # seconds; mutations inside this window share a restart
_last_ok_reload = 0.0
_pending_reload: threading.Timer | None = None


def _do_reload() -> tuple[bool, str]:
    """The actual validate-then-restart sequence. Caller holds no lock."""
    try:
        cfg = build_config()
        fd, tmp = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w") as f:
            json.dump(cfg, f)
        try:
            if available():
                ok, msg = validate(tmp)
                if not ok:
                    db.log_event(
                        f"Reload aborted, invalid config: {msg[:400]}",
                        kind="xray", level="error")
                    return False, msg
        finally:
            os.unlink(tmp)

        stop()
        started = start()
        if started:
            return True, "reloaded"
        return False, "xray unavailable (control plane still running)"
    except Exception as e:
        db.log_event(f"Reload error: {e}", kind="xray", level="error")
        return False, str(e)


def _trailing_reload() -> None:
    """Apply the last state of a coalesced burst once the window closes."""
    global _pending_reload, _last_ok_reload
    with _RELOAD_LOCK:
        _pending_reload = None
    # Run reload outside the lock — holding both RELOAD_LOCK and Xray's
    # process lock at once could deadlock with concurrent reload() calls.
    ok, _ = _do_reload()
    if ok:
        with _RELOAD_LOCK:
            _last_ok_reload = time.time()


def reload() -> tuple[bool, str]:
    """
    Rebuild config and restart xray.

    Xray has no SIGHUP reload, so we validate the new config into a temp file
    *before* touching the live one. If validation fails the running process is
    left completely untouched.

    Mutations arriving within RELOAD_WINDOW of a successful restart are
    coalesced into one trailing restart instead of each paying their own.
    The whole sequence is serialized: two concurrent callers can never
    interleave stop()/start() on the live process.
    """
    global _last_ok_reload, _pending_reload
    with _RELOAD_LOCK:
        now = time.time()
        if now - _last_ok_reload < _RELOAD_WINDOW:
            if _pending_reload is None:
                t = threading.Timer(_RELOAD_WINDOW, _trailing_reload)
                t.name = "xray-coalesced-reload"
                t.daemon = True
                t.start()
                _pending_reload = t
            return True, "queued (coalesced)"
        ok, msg = _do_reload()
        if ok:
            _last_ok_reload = time.time()
        return ok, msg


# ── stats ────────────────────────────────────────────────────────────────────

def stats_query(pattern: str = "", reset: bool = False) -> dict[str, int]:
    """
    Run `xray api statsquery`. Returns {stat_name: value}.
    Empty dict when xray/API is unavailable — callers must tolerate that.
    """
    cmd = [XRAY_BIN, "api", "statsquery", f"--server={API_ADDR}"]
    if reset:
        cmd.append("-reset")
    if pattern:
        cmd.append(f"-pattern={pattern}")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if r.returncode != 0:
            return {}
        data = json.loads(r.stdout or "{}")
    except Exception:
        return {}

    out: dict[str, int] = {}
    for item in data.get("stat", []) or []:
        name = item.get("name")
        if name:
            out[name] = int(item.get("value", 0) or 0)
    return out


def user_traffic_delta() -> dict[str, tuple[int, int]]:
    """
    Read *and reset* per-user counters.
    Returns {email: (uplink_delta, downlink_delta)}.
    """
    raw = stats_query("user>>>", reset=True)
    agg: dict[str, list[int]] = {}
    for name, val in raw.items():
        # user>>>{email}>>>traffic>>>uplink
        parts = name.split(">>>")
        if len(parts) != 4:
            continue
        email, direction = parts[1], parts[3]
        slot = agg.setdefault(email, [0, 0])
        if direction == "uplink":
            slot[0] += val
        elif direction == "downlink":
            slot[1] += val
    return {k: (v[0], v[1]) for k, v in agg.items()}
