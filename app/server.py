"""
ULTRA GAMING VPN — control-plane HTTP server.

Pure stdlib (ThreadingHTTPServer) so the image stays tiny and dependency-free.
Listens on 127.0.0.1:8888; nginx is the only thing in front of it.

Routes
------
  GET  /health                     liveness
  POST /api/login                  -> {token}
  GET  /api/bootstrap              panel bootstrap payload (auth)
  GET  /api/stats                  live snapshot (auth)
  GET  /api/stream                 SSE live snapshot (auth via ?t=)
  GET  /api/history?window=24h     time-series (auth)
  GET  /api/heatmap?days=7         hourly traffic heatmap (auth)
  GET  /api/top                    top users (auth)
  GET  /api/events                 recent events (auth)
  GET  /api/settings  POST         runtime settings (auth)
  GET  /api/users     POST         list / create (auth)
  GET|PATCH|DELETE /api/users/<id> (auth)
  POST /api/users/<id>/reset       rotate credentials (auth)
  GET  /api/users/<id>/configs     catalog + sub links (auth)
  POST /api/xray/reload            (auth)
  GET  /api/profiles               game profiles (public-ish, auth)
  POST /api/terminal               console commands (auth)
  GET  /api/probe                  latency probe target (public, tiny)
  GET  /api/ipcheck                TCP RTT to pinned CDN IPs (auth)
  GET  /__ws                       WebSocket echo for tunnel RTT (public)
  GET  /api/locations              full country list + status (auth)
  POST /api/locations/<cc>/start|stop|pin|unpin  (auth)
  GET  /sub/<token>[?format=]      subscription (public, token-scoped)
  GET  /u/<token>/api              user portal data (public, token-scoped)
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import queue
import re
import secrets
import socket
import sqlite3
import struct
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import (auth, db, decoy, gamify, links, locations, metrics, paths,
               profiles, reality, tunnel, xray)

BIND = ("127.0.0.1", int(os.environ.get("API_PORT", "8888")))
CF_HOST = os.environ.get("CF_WORKER_HOST", "").strip()
PUBLIC_HOST = os.environ.get("PUBLIC_HOST", "").strip()
# Railway injects this; it is the *.up.railway.app name for the service.
# Railway injects this only when the service actually has a generated
# *.up.railway.app domain. A service that only has a custom domain attached
# will not have it, which is why alternates were silently missing.
RAILWAY_DOMAIN = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "").strip()
# Some deployments expose it under the static-URL name instead.
if not RAILWAY_DOMAIN:
    RAILWAY_DOMAIN = os.environ.get("RAILWAY_STATIC_URL", "").strip()
# Manual override / addition, comma separated.
ALT_HOSTS = [h.strip() for h in
             os.environ.get("ALT_HOSTS", "").split(",") if h.strip()]

_BOOT_TS = time.time()

_ID_RE = re.compile(r"^/api/users/(\d+)$")
_ACTION_RE = re.compile(
    r"^/api/users/(\d+)/(reset|configs|history|weekly|boost|unboost)$")
_SUB_RE = re.compile(r"^/sub/([A-Za-z0-9_-]{8,64})$")
_PORTAL_RE = re.compile(r"^/u/([A-Za-z0-9_-]{8,64})/api$")
_PORTAL_ACT_RE = re.compile(
    r"^/u/([A-Za-z0-9_-]{8,64})/(boost|weekly|history)$")
_TRIAL_ID_RE = re.compile(r"^/api/trials/(\d+)$")
_TRIAL_CLAIM_RE = re.compile(r"^/t/([A-Za-z0-9_-]{8,64})/claim$")
_TRIAL_INFO_RE = re.compile(r"^/t/([A-Za-z0-9_-]{8,64})/api$")
_LOC_RE = re.compile(r"^/api/locations/([a-z]{2})/(start|stop|pin|unpin)$")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "UltraGaming"
    sys_version = ""

    def log_message(self, *a):  # silence
        pass

    # ── helpers ──────────────────────────────────────────────────────────
    @property
    def client_ip(self) -> str:
        """
        True visitor address.

        Behind Cloudflare, CF-Connecting-IP is the only trustworthy source:
        X-Forwarded-For then contains Cloudflare's edge address. nginx already
        folds this into X-Real-IP, but the header is checked directly too so
        the control plane is correct even if it is reached without nginx.
        """
        return (self.headers.get("CF-Connecting-IP")
                or self.headers.get("X-Real-IP")
                or self.headers.get("X-Forwarded-For", "").split(",")[0].strip()
                or self.client_address[0])

    def host_for_links(self) -> str:
        if PUBLIC_HOST:
            return PUBLIC_HOST
        h = self.headers.get("X-Forwarded-Host") or self.headers.get("Host", "")
        return h.split(",")[0].split(":")[0].strip() or "localhost"

    def alt_hosts(self) -> list[str]:
        """
        Alternate hostnames to also emit configs for.

        A deployment usually answers on two names: the custom domain and the
        original *.up.railway.app one. Shipping both means a player keeps a
        working config when one of them is unreachable for their ISP, without
        having to ask for a new subscription.

        Sources: ALT_HOSTS (manual, comma separated) and
        RAILWAY_PUBLIC_DOMAIN (injected by Railway).

        The request's own Host header is deliberately NOT used. Behind nginx
        it is frequently an internal name or a bare IP, and emitting a config
        pointing at 127.0.0.1 would be worse than useless.
        """
        primary = self.host_for_links().lower()
        out: list[str] = []

        # Tunnel hostname (xxx.trycloudflare.com) is auto-discovered by
        # start.sh when cloudflared is available — no manual config.
        tunnel_host = ""
        try:
            tunnel_host = tunnel.get_tunnel_host() or ""
        except Exception:
            tunnel_host = ""

        for raw in list(ALT_HOSTS) + [RAILWAY_DOMAIN] + [tunnel_host]:
            h = (raw or "").strip().lower()
            h = h.split("://")[-1].split("/")[0].split(":")[0]
            if not _is_public_host(h) or h == primary or h in out:
                continue
            out.append(h)
        return out

    def _send(self, code: int, body: bytes, ctype: str,
              extra: dict | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

    def json(self, data, code: int = 200, extra: dict | None = None) -> None:
        self._send(code, json.dumps(data, ensure_ascii=False).encode(),
                   "application/json; charset=utf-8", extra)

    def text(self, s: str, code: int = 200, ctype: str = "text/plain") -> None:
        self._send(code, s.encode(), f"{ctype}; charset=utf-8")

    def err(self, code: int, msg: str) -> None:
        self.json({"error": msg}, code)

    def body_json(self) -> dict:
        try:
            n = int(self.headers.get("Content-Length", "0") or 0)
        except ValueError:
            return {}
        if n <= 0 or n > 1_000_000:
            return {}
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return {}

    def q(self) -> dict:
        return dict(urllib.parse.parse_qsl(
            urllib.parse.urlparse(self.path).query))

    def token(self) -> str | None:
        h = self.headers.get("Authorization", "")
        if h.startswith("Bearer "):
            return h[7:].strip()
        return self.q().get("t")

    def require_admin(self) -> bool:
        if auth.verify(self.token()):
            return True
        self.err(401, "unauthorized")
        return False

    # ── routing ──────────────────────────────────────────────────────────
    def do_GET(self):
        p = urllib.parse.urlparse(self.path).path
        try:
            self.route_get(p)
        except BrokenPipeError:
            pass
        except Exception as e:
            try:
                self.err(500, f"internal error: {e}")
            except Exception:
                pass

    do_HEAD = do_GET

    def do_POST(self):
        p = urllib.parse.urlparse(self.path).path
        try:
            self.route_post(p)
        except BrokenPipeError:
            pass
        except Exception as e:
            try:
                self.err(500, f"internal error: {e}")
            except Exception:
                pass

    def do_PATCH(self):
        p = urllib.parse.urlparse(self.path).path
        m = _ID_RE.match(p)
        if not m:
            return self.err(404, "not found")
        if not self.require_admin():
            return
        self.patch_user(int(m.group(1)))

    def do_DELETE(self):
        p = urllib.parse.urlparse(self.path).path
        m = _ID_RE.match(p)
        if m:
            if not self.require_admin():
                return
            uid = int(m.group(1))
            if not db.get_user(uid):
                return self.err(404, "user not found")
            db.delete_user(uid)
            xray.reload()
            return self.json({"ok": True})

        m = _TRIAL_ID_RE.match(p)
        if m:
            if not self.require_admin():
                return
            tid = int(m.group(1))
            if not db.trial_get_by_id(tid):
                return self.err(404, "trial not found")
            db.trial_delete(tid)
            return self.json({"ok": True})

        return self.err(404, "not found")

    # ── GET routes ───────────────────────────────────────────────────────
    def route_get(self, p: str):
        if p == "/health":
            # Version in the body makes it trivial to confirm which build is
            # actually live, without logging in or trusting a cached panel.
            return self.text(f"ok v{_version()}\n")

        if p == "/version":
            try:
                _tunnel = tunnel.get_tunnel_host()
            except Exception:
                _tunnel = None
            return self.json({
                "version": _version(),
                "prefix": paths.PREFIX,
                "xray": xray.is_alive(),
            # Country exits, including ones still bootstrapping, so the
            # panel can show progress rather than an empty list.
            "locations": locations.snapshot(),
                "tunnel": _tunnel,
                "tunnel_available": bool(_tunnel),
                "started": int(_BOOT_TS),
                "uptime_s": int(time.time() - _BOOT_TS),
            })

        if p == "/api/probe":
            # ultra-small payload for RTT measurement
            return self.json({"t": time.time()})

        if p == "/__ws":
            # Tiny public WebSocket echo for tunnel latency measurement.
            # The browser connects here, we bounce one frame per round trip,
            # and the client times it — the result is RTT over the real
            # path (TLS + Cloudflare + nginx), unlike an HTTP probe which
            # measures a short-lived request.
            return self.ws_echo()

        m = _SUB_RE.match(p)
        if m:
            return self.subscription(m.group(1))

        m = _PORTAL_RE.match(p)
        if m:
            return self.portal(m.group(1))

        m = _PORTAL_ACT_RE.match(p)
        if m:
            return self.portal_action(m.group(1), m.group(2), post=False)

        m = _TRIAL_INFO_RE.match(p)
        if m:
            return self.trial_info(m.group(1))

        if p == "/api/meta":
            from . import __version__
            return self.json({
                "version": __version__,
                "auth_required": True,
                "configured": auth.configured(),
                "host": self.host_for_links(),
                "cf_host": CF_HOST or None,
            })

        # everything below requires admin
        if p.startswith("/api/"):
            if p == "/api/stream":
                return self.stream()
            if not self.require_admin():
                return

        if p == "/api/bootstrap":
            return self.bootstrap()
        if p == "/api/stats":
            return self.json(metrics.latest())
        if p == "/api/history":
            return self.json(metrics.history(self.q().get("window", "24h")))
        if p == "/api/heatmap":
            days = max(1, min(30, int(self.q().get("days", "7") or 7)))
            return self.json(metrics.heatmap(days))
        if p == "/api/ipcheck":
            return self.json(self.ip_check())
        if p == "/api/top":
            return self.json(metrics.top_users(
                max(1, min(50, int(self.q().get("limit", "10") or 10)))))
        if p == "/api/events":
            lim = max(1, min(200, int(self.q().get("limit", "50") or 50)))
            rows = db.query(
                "SELECT * FROM events ORDER BY ts DESC LIMIT ?", (lim,))
            return self.json([dict(r) for r in rows])
        if p == "/api/reality":
            try:
                return self.json({
                    "enabled": reality.enabled(),
                    "dest": reality.dest(),
                    "sni": reality.server_name(),
                    "fp": reality.fingerprint(),
                    "port": reality.reality_port(),
                    "host": reality.reality_host() or None,
                    "pbk": reality.public_key() or None,
                    "sid": reality.short_id() or None,
                })
            except Exception as e:
                return self.err(500, str(e))
        if p == "/api/settings":
            return self.json(db.all_settings())
        if p == "/api/profiles":
            return self.json(profiles.listing())
        if p == "/api/games":
            return self.json(profiles.games())
        if p == "/api/locations":
            return self.json(self.locations_payload())
        if p == "/api/trials":
            host = self.host_for_links()
            out = []
            for t in db.trial_list():
                d = dict(t)
                d["url"] = f"https://{host}/t/{t['code']}/"
                out.append(d)
            return self.json(out)
        if p == "/api/users":
            return self.json([self.decorate(u) for u in db.list_users()])

        m = _ID_RE.match(p)
        if m:
            u = db.get_user(int(m.group(1)))
            return self.json(self.decorate(u)) if u else self.err(404, "not found")

        m = _ACTION_RE.match(p)
        if m:
            uid, action = int(m.group(1)), m.group(2)
            if action == "configs":
                return self.user_configs(uid)
            if action == "history":
                if not db.get_user(uid):
                    return self.err(404, "user not found")
                w = self.q().get("window", "24h")
                return self.json({
                    "window": w,
                    "series": db.user_history(uid, w),
                })
            if action == "weekly":
                if not db.get_user(uid):
                    return self.err(404, "user not found")
                return self.json(self.weekly_report(uid))
            if action == "boost":
                return self.json(db.boost_status(uid))

        if p == "/api/export":
            return self.export()

        # ── Decoy (dynamic) ──────────────────────────────────────────
        # Everything that is not an API/sub/portal path and reached the
        # control plane via nginx's catch-all "/" is a scanner or a bare
        # domain visit — serve a random corporate page rather than a 404.
        # Respects the decoy_enabled setting the panel can toggle.
        # Real API 404s must stay JSON — don't swallow them.
        if p.startswith(("/api/", "/sub/", "/u/", "/t/")):
            return self.err(404, "not found")
        if db.get_setting("decoy_enabled", True):
            return self.decoy()

        return self.err(404, "not found")

    # ── POST routes ──────────────────────────────────────────────────────
    def route_post(self, p: str):
        if p == "/api/login":
            return self.login()

        # public, token-scoped
        m = _TRIAL_CLAIM_RE.match(p)
        if m:
            return self.trial_claim(m.group(1))

        m = _PORTAL_ACT_RE.match(p)
        if m:
            return self.portal_action(m.group(1), m.group(2), post=True)

        if not self.require_admin():
            return

        if p == "/api/trials":
            b = self.body_json()
            t = db.trial_create(
                quota_gb=_as_float(b.get("quota_gb"), 1.0) or 1.0,
                hours=_as_int(b.get("hours"), 24) or 24,
                max_claims=_as_int(b.get("max_claims"), 10) or 10,
                per_day=_as_int(b.get("per_day"), 5) or 5,
            )
            host = self.host_for_links()
            t["url"] = f"https://{host}/t/{t['code']}/"
            return self.json(t, 201)

        m = _TRIAL_ID_RE.match(p)
        if m:
            tid = int(m.group(1))
            if not db.trial_get_by_id(tid):
                return self.err(404, "trial not found")
            b = self.body_json()
            if "enabled" in b:
                db.trial_toggle(tid, bool(b["enabled"]))
            return self.json(db.trial_get_by_id(tid))

        if p == "/api/users":
            return self.create_user()
        if p == "/api/xray/reload":
            ok, msg = xray.reload()
            return self.json({"ok": ok, "message": msg})

        m = _LOC_RE.match(p)
        if m:
            code, action = m.group(1), m.group(2)
            if action == "start":
                return self.json(locations.start_code(code))
            if action == "stop":
                return self.json(locations.stop_code(code))
            if action == "pin":
                ip = (self.body_json().get("ip") or "").strip()
                return self.json(locations.pin_exit(code, ip))
            if action == "unpin":
                return self.json(locations.unpin_exit(code))
        if p == "/api/settings":
            body = self.body_json()
            for k, v in body.items():
                if k in ("turbo_mode", "decoy_enabled", "alert_cpu",
                         "alert_quota_pct"):
                    db.set_setting(k, v)
                elif k == "cf_ips":
                    # Pinned CDN IPs ("آیپی ثابت") — normalized, only
                    # public IPv4s are kept.
                    db.set_setting("cf_ips", links.normalize_ips(v))
                elif k == "smart_fragment":
                    # Anti-DPI fragmentation preset; unknown modes fall
                    # back to off rather than producing garbage links.
                    mode = str(v or "").strip().lower()
                    if mode not in links.FRAGMENT_MODES:
                        mode = ""
                    db.set_setting("smart_fragment", mode)
                elif k == "reality_enabled":
                    reality.toggle(bool(v))
                    if bool(v):
                        xray.reload()
                        db.log_event("REALITY enabled", kind="settings")
                    else:
                        xray.reload()
                        db.log_event("REALITY disabled", kind="settings")
                elif k in ("reality_dest", "reality_sni", "reality_fp", "reality_port", "reality_host"):
                    # REALITY fields — validated before saving
                    dest_v = str(body.get("reality_dest", reality.dest()) or "").strip()
                    sni_v = str(body.get("reality_sni", reality.server_name()) or "").strip()
                    fp_v = str(body.get("reality_fp", reality.fingerprint()) or "").strip().lower()
                    port_v = str(body.get("reality_port", reality.reality_port()) or "").strip()
                    host_v = str(body.get("reality_host", reality.reality_host()) or "").strip()
                    ok, msg = reality.validate_settings(dest_v, sni_v, fp_v, port_v)
                    if not ok:
                        return self.err(400, msg)
                    if "reality_dest" in body:
                        db.set_setting("reality_dest", dest_v or reality.DEFAULT_DEST)
                    if "reality_sni" in body:
                        db.set_setting("reality_sni", sni_v or reality.DEFAULT_SNI)
                    if "reality_fp" in body:
                        db.set_setting("reality_fp", fp_v or reality.DEFAULT_FP)
                    if "reality_port" in body and port_v:
                        db.set_setting("reality_port", port_v)
                        xray.reload()
                    if "reality_host" in body:
                        # env var takes precedence, but store for display
                        db.set_setting("reality_host", host_v)
            if "turbo_mode" in body:
                xray.reload()
                db.log_event(
                    f"Turbo mode {'enabled' if body['turbo_mode'] else 'disabled'}",
                    kind="settings")
            # REALITY port change needs reload even when turbo didn't
            if "reality_port" in body and "turbo_mode" not in body:
                # already reloaded above if port changed; ensure once
                pass
            return self.json(db.all_settings())
        if p == "/api/reality/rotate":
            # Rotate REALITY keypair (admin only, already past require_admin)
            priv, pub = reality.rotate_keys()
            xray.reload()
            db.log_event("REALITY keys rotated", kind="settings", level="warn")
            return self.json({"ok": True, "pbk": pub[:18] + "…", "sid": reality.short_id()})
        if p == "/api/terminal":
            return self.terminal()

        m = _ACTION_RE.match(p)
        if m:
            uid, action = int(m.group(1)), m.group(2)
            if action == "reset":
                return self.reset_user(uid)
            if action == "boost":
                if not db.get_user(uid):
                    return self.err(404, "user not found")
                mins = max(5, min(240, _as_int(self.body_json().get("minutes"),
                                               30) or 30))
                st = db.boost_start(uid, mins)
                xray.reload()
                return self.json(st)
            if action == "unboost":
                db.boost_stop(uid)
                xray.reload()
                return self.json({"active": False, "remaining": 0})

        # Decoy for non-API POSTs that hit the catch-all (scanners)
        # Real API 404s must stay JSON.
        if p.startswith(("/api/", "/sub/", "/u/", "/t/")):
            return self.err(404, "not found")
        if db.get_setting("decoy_enabled", True):
            return self.decoy()
        return self.err(404, "not found")

    # ── handlers ─────────────────────────────────────────────────────────
    def login(self):
        ip = self.client_ip
        if auth.throttled(ip):
            return self.err(429, "too many attempts, wait a few minutes")
        if not auth.configured():
            return self.err(503, "ADMIN_PASS is not set on the server")
        b = self.body_json()
        if auth.check_password(b.get("username", ""), b.get("password", "")):
            auth.clear_fails(ip)
            db.log_event(f"Admin login from {ip}", kind="auth")
            return self.json({"token": auth.issue(), "ttl": auth.TTL})
        auth.record_fail(ip)
        db.log_event(f"Failed login from {ip}", kind="auth", level="warn")
        time.sleep(0.7)
        return self.err(401, "invalid credentials")

    def bootstrap(self):
        host = self.host_for_links()
        users = db.list_users()
        try:
            _tunnel = tunnel.get_tunnel_host()
        except Exception:
            _tunnel = None
        # REALITY status for Settings page
        try:
            _reality = {
                "enabled": reality.enabled(),
                "dest": reality.dest(),
                "sni": reality.server_name(),
                "fp": reality.fingerprint(),
                "port": reality.reality_port(),
                "host": reality.reality_host() or None,
                "pbk": (reality.public_key()[:18] + "…") if reality.public_key() else None,
                "sid": reality.short_id() or None,
            }
        except Exception:
            _reality = {"enabled": False}
        return self.json({
            "host": host,
            "cf_host": CF_HOST or None,
            "tunnel_host": _tunnel,
            "hosts": [{"host": h, "label": lbl} for h, lbl in
                      links.host_list(host, CF_HOST or None,
                                      self.alt_hosts())],
            "railway_domain": RAILWAY_DOMAIN or None,
            "alt_hosts": list(ALT_HOSTS),
            "paths": paths.ALL,
            "prefix": paths.PREFIX,
            "reality": _reality,
            # Drives the transport picker in the user modal. Built from a
            # real catalog so the options are exactly the configs that
            # exist right now, including one row per verified country.
            "selectable": self.selectable_entries(),
            "settings": db.all_settings(),
            "profiles": profiles.listing(),
            "games": profiles.games(),
            "stats": metrics.latest(),
            "users": [self.decorate(u) for u in users],
            "user_count": len(users),
            "active_count": len(db.active_users()),
            "xray": xray.is_alive(),
            # Country exits, including ones still bootstrapping, so the
            # panel can show progress rather than an empty list.
            "locations": locations.snapshot(),
            "ranks": [{"name": r[0], "xp": r[1], "color": r[2], "icon": r[3]}
                      for r in gamify.RANKS],
            "server_time": int(time.time()),
            "version": _version(),
        })

    def decorate(self, u: dict | None) -> dict:
        if not u:
            return {}
        d = dict(u)
        total = d["used_up"] + d["used_down"]
        d["used_total"] = total
        d["quota_pct"] = (round(total / d["quota_bytes"] * 100, 1)
                          if d["quota_bytes"] else None)
        d["rank"] = gamify.rank_for(d["xp"])
        d["achievements"] = gamify.summary(d["id"])
        d["expired"] = bool(d["expires_at"]) and d["expires_at"] < time.time()
        d["days_left"] = (max(0, int((d["expires_at"] - time.time()) // 86400))
                          if d["expires_at"] else None)
        d["sub_url"] = f"/sub/{d['sub_token']}"
        d["portal_url"] = f"/u/{d['sub_token']}/"
        d["boost"] = db.boost_status(d["id"])
        # Normalised here so every caller — the user list, the configs
        # endpoint, the player portal — sees the same parsed list rather
        # than the raw comma-separated column.
        d["allowed_kinds"] = links.parse_kinds(d.get("allowed_kinds"))
        return d

    def create_user(self):
        b = self.body_json()
        name = _as_name(b.get("username"))
        if not re.fullmatch(r"[A-Za-z0-9_.-]{2,32}", name):
            return self.err(400, "username must be 2-32 chars [A-Za-z0-9_.-]")
        if db.one("SELECT 1 FROM users WHERE username=?", (name,)):
            return self.err(409, "username already exists")
        try:
            u = db.create_user(
                name,
                quota_gb=_as_float(b.get("quota_gb")),
                days=_as_int(b.get("days")),
                note=_as_str(b.get("note"))[:200],
            )
            # Transport selection is stored separately: create_user() has a
            # fixed signature and this is optional, so a caller that omits
            # it keeps the "everything" default.
            _kinds = _clean_kinds(b.get("allowed_kinds"))
            if _kinds:
                u = db.update_user(u["id"], allowed_kinds=_kinds) or u
        except sqlite3.IntegrityError:
            return self.err(409, "username already exists")
        except Exception as e:
            return self.err(400, f"could not create user: {e}")
        xray.reload()
        return self.json(self.decorate(u), 201)

    def patch_user(self, uid: int):
        if not db.get_user(uid):
            return self.err(404, "user not found")
        b = self.body_json()
        fields: dict = {}
        if "username" in b:
            n = _as_name(b["username"])
            if not re.fullmatch(r"[A-Za-z0-9_.-]{2,32}", n):
                return self.err(400, "invalid username")
            clash = db.one("SELECT id FROM users WHERE username=? AND id<>?",
                           (n, uid))
            if clash:
                return self.err(409, "username already exists")
            fields["username"] = n
        if "quota_gb" in b:
            g = _as_float(b["quota_gb"])
            fields["quota_bytes"] = int(g * 1024 ** 3) if g > 0 else 0
        if "days" in b:
            d = _as_int(b["days"])
            fields["expires_at"] = int(time.time() + d * 86400) if d > 0 else 0
        if "allowed_kinds" in b:
            fields["allowed_kinds"] = _clean_kinds(b["allowed_kinds"])
        if "enabled" in b:
            fields["enabled"] = 1 if b["enabled"] else 0
        if "note" in b:
            fields["note"] = _as_str(b["note"])[:200]
        if b.get("reset_traffic"):
            fields["used_up"] = 0
            fields["used_down"] = 0
        try:
            u = db.update_user(uid, **fields)
        except sqlite3.IntegrityError:
            return self.err(409, "username already exists")
        xray.reload()
        return self.json(self.decorate(u))

    def reset_user(self, uid: int):
        if not db.get_user(uid):
            return self.err(404, "user not found")
        u = db.update_user(uid, uuid=db.new_uuid(),
                           trojan_pass=db.new_token(16),
                           ss_pass=db.new_token(16),
                           sub_token=db.new_token(20))
        xray.reload()
        db.log_event(f"Credentials rotated for user #{uid}", kind="user")
        return self.json(self.decorate(u))

    def locations_payload(self) -> dict:
        """Everything the Locations page renders, in one response."""
        snap = locations.snapshot()
        hist: dict[str, list[dict]] = {}
        for row in snap:
            if row["enabled"]:
                hist[row["code"]] = locations.exit_history(row["code"], 5)
        return {
            "locations": snap,
            "history": hist,
            "max": locations.MAX_LOCATIONS,
            "per_location_ram_mb": 40,
            "tor_available": locations.available(),
            "enabled_count": sum(1 for r in snap if r["enabled"]),
            "excluded_count": len(locations.EXCLUDE),
            "relay_data": locations.relay_data(),
        }

    def ip_check(self) -> dict:
        """TCP reachability + RTT to each pinned CDN IP, from the server.

        A sanity probe only — it measures the Railway->IP path, not the
        player's ISP path. The real test is the client connecting.
        """
        out = []
        for ip in links.pinned_ips():
            t0 = time.time()
            try:
                with socket.create_connection((ip, 443), timeout=2.5):
                    out.append({"ip": ip, "reachable": True,
                                "ms": round((time.time() - t0) * 1000)})
            except Exception:
                out.append({"ip": ip, "reachable": False, "ms": None})
        return {"ips": out, "count": len(out)}

    def selectable_entries(self, lang: str = "en") -> list[dict]:
        """
        Every config a user could be granted, as {id, label, kind}.

        Generated from a real catalog against a throwaway user so it can
        never drift from what subscriptions actually contain. Credentials
        are not included: only the id and the label are returned.
        """
        stub = {"id": 0, "username": "x",
                "uuid": "00000000-0000-0000-0000-000000000000",
                "trojan_pass": "x", "quota_bytes": 0, "expires_at": 0,
                "used_up": 0, "used_down": 0, "allowed_kinds": ""}
        try:
            cat = links.catalog(stub, self.host_for_links(),
                                CF_HOST or None, None, self.alt_hosts(),
                                lang)
        except Exception:
            return []
        return [{"id": c["id"], "label": c["label"], "kind": c["kind"],
                 "via": c.get("via", ""), "note": c.get("note", "")}
                for c in cat]

    def user_configs(self, uid: int):
        u = db.get_user(uid)
        if not u:
            return self.err(404, "user not found")
        host = self.host_for_links()
        prof = self.q().get("profile")
        lang = self.q().get("lang", "en")
        alts = self.alt_hosts()
        cat = links.catalog(u, host, CF_HOST or None, prof, alts, lang)
        # The panel needs both the current selection and the full set of
        # choices, because a kind the user cannot currently receive (a
        # location that has not verified) must still render as a checkbox.
        return self.json({
            "user": self.decorate(u),
            "allowed_kinds": links.parse_kinds(u.get("allowed_kinds")),
            "selectable": self.selectable_entries(lang),
            "configs": cat,
            "sub": {
                "base64": f"https://{host}/sub/{u['sub_token']}",
                "clash": f"https://{host}/sub/{u['sub_token']}?format=clash",
                "singbox": f"https://{host}/sub/{u['sub_token']}?format=singbox",
                "raw": f"https://{host}/sub/{u['sub_token']}?format=raw",
            },
            "portal": f"https://{host}/u/{u['sub_token']}/",
        })

    def subscription(self, token: str):
        u = db.get_user_by_token(token)
        if not u:
            return self.err(404, "not found")
        host = self.host_for_links()
        fmt = (self.q().get("format") or "base64").lower()
        prof = self.q().get("profile")
        cf = CF_HOST or None
        alts = self.alt_hosts()
        # ?info=0 drops the quota/expiry entries for clients that dislike
        # unreachable servers in their list.
        want_info = self.q().get("info", "1") not in ("0", "false", "no")

        headers = {
            "Profile-Update-Interval": "12",
            # Every modern client reads this; the entries added to the body
            # are a fallback for the ones that only show it if you dig.
            "Subscription-Userinfo": (
                f"upload={u['used_up']}; download={u['used_down']}; "
                f"total={u['quota_bytes']}; expire={u['expires_at']}"),
            "Profile-Title": f"ULTRA GAMING · {u['username']}",
            "Profile-Web-Page-Url": f"https://{host}/u/{token}/",
        }
        db.execute("UPDATE users SET last_seen=? WHERE id=?",
                   (int(time.time()), u["id"]))

        if not u["enabled"]:
            return self._send(403, b"subscription disabled", "text/plain",
                              headers)

        if fmt == "clash":
            body = links.sub_clash(u, host, cf, prof, alts).encode()
            return self._send(200, body, "text/yaml; charset=utf-8", headers)
        if fmt in ("singbox", "sing-box"):
            body = links.sub_singbox(u, host, cf, prof, alts).encode()
            return self._send(200, body, "application/json; charset=utf-8",
                              headers)
        if fmt == "raw":
            body = links.sub_raw(u, host, cf, prof, alts, want_info).encode()
            return self._send(200, body, "text/plain; charset=utf-8", headers)
        body = links.sub_base64(u, host, cf, prof, alts, want_info).encode()
        return self._send(200, body, "text/plain; charset=utf-8", headers)

    def portal(self, token: str):
        u = db.get_user_by_token(token)
        if not u:
            return self.err(404, "not found")
        host = self.host_for_links()
        prof = self.q().get("profile")
        d = self.decorate(u)
        # never leak other users or server internals here
        return self.json({
            "username": d["username"],
            "enabled": bool(d["enabled"]),
            "rank": d["rank"],
            "achievements": d["achievements"],
            "used_up": d["used_up"],
            "used_down": d["used_down"],
            "used_total": d["used_total"],
            "quota_bytes": d["quota_bytes"],
            "quota_pct": d["quota_pct"],
            "days_left": d["days_left"],
            "expires_at": d["expires_at"],
            "allowed_kinds": links.parse_kinds(u.get("allowed_kinds")),
            "selectable_kinds": list(links.SELECTABLE_KINDS),
            "configs": links.catalog(u, host, CF_HOST or None, prof,
                                     self.alt_hosts(),
                                     self.q().get("lang", "en")),
            "profiles": profiles.listing(),
            "games": profiles.games(),
            "boost": db.boost_status(u["id"]),
            "sub": {
                "base64": f"https://{host}/sub/{token}",
                "clash": f"https://{host}/sub/{token}?format=clash",
                "singbox": f"https://{host}/sub/{token}?format=singbox",
            },
            "server": {"score": metrics.latest().get("score", 0),
                       "uptime": metrics.latest().get("uptime", "")},
        })

    # ── weekly report (idea #14) ─────────────────────────────────────────
    def weekly_report(self, uid: int) -> dict:
        u = db.get_user(uid)
        if not u:
            return {}
        w = db.user_weekly(uid)
        rank = gamify.rank_for(u["xp"])
        ach = gamify.summary(uid)

        days = ["Monday", "Tuesday", "Wednesday", "Thursday",
                "Friday", "Saturday", "Sunday"]
        highlights = []
        if w["total"] > 0:
            highlights.append(
                f"You moved {_h(w['total'])} this week.")
        if w["change_pct"] is not None:
            if w["change_pct"] > 5:
                highlights.append(
                    f"That is {abs(w['change_pct'])}% more than last week.")
            elif w["change_pct"] < -5:
                highlights.append(
                    f"That is {abs(w['change_pct'])}% less than last week.")
            else:
                highlights.append("Almost identical to last week.")
        if w["busiest_day"] is not None:
            highlights.append(
                f"{days[w['busiest_day']]} was your busiest day.")
        if w["busiest_hour"] is not None:
            h = w["busiest_hour"]
            highlights.append(
                f"You play most around {h:02d}:00.")
        if w["active_days"]:
            highlights.append(
                f"Active on {w['active_days']} of the last 7 days.")
        recent = [a for a in ach["unlocked"]][-3:]
        if recent:
            highlights.append(
                "Unlocked: " + ", ".join(a["title"] for a in recent) + ".")

        # projection: when will the quota run out at this rate?
        projection = None
        if u["quota_bytes"] and w["total"] > 0:
            left = u["quota_bytes"] - (u["used_up"] + u["used_down"])
            per_day = w["total"] / 7
            if left > 0 and per_day > 0:
                projection = {
                    "days_left": round(left / per_day, 1),
                    "bytes_left": left,
                    "per_day": int(per_day),
                }
            elif left <= 0:
                projection = {"days_left": 0, "bytes_left": 0,
                              "per_day": int(per_day)}

        return {
            "username": u["username"],
            "rank": rank,
            "achievements": {"count": ach["count"], "total": ach["total"]},
            "traffic": w,
            "projection": projection,
            "highlights": highlights,
            "generated_at": int(time.time()),
        }

    # ── trials (idea #19) ────────────────────────────────────────────────
    def trial_info(self, code: str):
        t = db.trial_get(code)
        if not t:
            return self.err(404, "not found")
        today = db.trial_claims_today(t["id"])
        remaining_total = max(0, t["max_claims"] - t["claims"])
        remaining_today = max(0, t["per_day"] - today)
        already = db.trial_claimed_by_ip(t["id"], self.client_ip)
        return self.json({
            "quota_gb": t["quota_gb"],
            "hours": t["hours"],
            "enabled": bool(t["enabled"]),
            "remaining_total": remaining_total,
            "remaining_today": remaining_today,
            "available": bool(t["enabled"]) and remaining_total > 0
            and remaining_today > 0 and not already,
            "already_claimed": already,
        })

    def trial_claim(self, code: str):
        t = db.trial_get(code)
        if not t:
            return self.err(404, "not found")
        if not t["enabled"]:
            return self.err(403, "this trial link is disabled")
        if t["claims"] >= t["max_claims"]:
            return self.err(410, "all trial slots have been used")
        if db.trial_claims_today(t["id"]) >= t["per_day"]:
            return self.err(429, "daily trial limit reached, try tomorrow")
        ip = self.client_ip
        if db.trial_claimed_by_ip(t["id"], ip):
            return self.err(409, "you already claimed a trial recently")

        # unique, non-guessable username
        base = f"trial-{secrets.token_hex(4)}"
        for _ in range(5):
            if not db.one("SELECT 1 FROM users WHERE username=?", (base,)):
                break
            base = f"trial-{secrets.token_hex(4)}"
        else:
            return self.err(500, "could not allocate a trial account")

        try:
            u = db.create_user(base, quota_gb=t["quota_gb"],
                               days=0, note=f"trial:{code}")
        except Exception as e:
            return self.err(500, f"could not create trial: {e}")

        # hour-precision expiry (create_user only takes whole days)
        expires = int(time.time() + t["hours"] * 3600)
        u = db.update_user(u["id"], expires_at=expires)
        db.trial_record(t["id"], u["id"], ip)
        xray.reload()
        db.log_event(f"Trial claimed from {ip}", kind="trial",
                     meta={"user_id": u["id"], "code": code})

        host = self.host_for_links()
        return self.json({
            "username": u["username"],
            "portal": f"https://{host}/u/{u['sub_token']}/",
            "sub": f"https://{host}/sub/{u['sub_token']}",
            "quota_gb": t["quota_gb"],
            "hours": t["hours"],
            "expires_at": expires,
        }, 201)

    # ── portal self-service (ideas #4, #7, #14) ──────────────────────────
    def portal_action(self, token: str, action: str, post: bool):
        u = db.get_user_by_token(token)
        if not u:
            return self.err(404, "not found")
        if action == "history":
            w = self.q().get("window", "24h")
            return self.json({"window": w,
                              "series": db.user_history(u["id"], w)})
        if action == "weekly":
            return self.json(self.weekly_report(u["id"]))
        if action == "boost":
            if not post:
                return self.json(db.boost_status(u["id"]))
            if not u["enabled"]:
                return self.err(403, "account is suspended")
            st = db.boost_status(u["id"])
            if st["active"]:
                return self.json(st)
            # players get a fixed 30-minute boost, no parameters
            st = db.boost_start(u["id"], 30)
            xray.reload()
            return self.json(st)
        return self.err(404, "not found")

    def export(self):
        fmt = (self.q().get("format") or "json").lower()
        rows = [self.decorate(u) for u in db.list_users()]
        if fmt == "csv":
            cols = ["id", "username", "uuid", "enabled", "used_up",
                    "used_down", "used_total", "quota_bytes", "expires_at",
                    "xp", "created_at", "last_seen", "note"]
            out = [",".join(cols)]
            for r in rows:
                out.append(",".join(
                    '"' + str(r.get(c, "")).replace('"', '""') + '"'
                    for c in cols))
            return self._send(200, "\n".join(out).encode(),
                              "text/csv; charset=utf-8",
                              {"Content-Disposition":
                               'attachment; filename="users.csv"'})
        return self._send(
            200, json.dumps(rows, indent=2, ensure_ascii=False).encode(),
            "application/json; charset=utf-8",
            {"Content-Disposition": 'attachment; filename="users.json"'})

    def decoy(self):
        """Serve a random decoy page (200, no-store)."""
        html = decoy.get_html()
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.end_headers()
        if self.command != "HEAD":
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

    def terminal(self):
        b = self.body_json()
        line = (b.get("cmd") or "").strip()
        if not line:
            return self.json({"out": ""})
        parts = line.split()
        cmd, args = parts[0].lower(), parts[1:]
        out = self.run_command(cmd, args)
        return self.json({"out": out})

    def run_command(self, cmd: str, args: list[str]) -> str:
        if cmd in ("help", "?"):
            return (
                "COMMANDS\n"
                "  help                 this text\n"
                "  stats                live system snapshot\n"
                "  score                gaming health score\n"
                "  users [n]            list users\n"
                "  user <name|id>       user detail\n"
                "  add <name> [gb] [d]  create user\n"
                "  del <name|id>        delete user\n"
                "  enable/disable <u>   toggle user\n"
                "  reset <u>            rotate credentials\n"
                "  top [n]              top consumers\n"
                "  events [n]           recent events\n"
                "  turbo on|off         low-latency mode\n"
                "  reload               restart xray\n"
                "  paths                transport paths\n"
                "  uptime               server uptime\n"
                "  clear                clear the console")
        if cmd == "stats":
            s = metrics.latest()
            return (f"CPU        {s['cpu']}%\n"
                    f"RAM        {s['memory']['percent']}% "
                    f"({s['memory']['used_mb']}/{s['memory']['total_mb']} MB)\n"
                    f"LOAD       {', '.join(str(x) for x in s['load'])}\n"
                    f"DOWN/UP    {_h(s['network']['rx_speed'])}/s  "
                    f"{_h(s['network']['tx_speed'])}/s\n"
                    f"TOTAL      ↓{_h(s['network']['rx_total'])}  "
                    f"↑{_h(s['network']['tx_total'])}\n"
                    f"SESSIONS   {s['connections']}\n"
                    f"XRAY       {'online' if s['xray'] else 'OFFLINE'}\n"
                    f"SCORE      {s['score']}/100\n"
                    f"UPTIME     {s['uptime']}")
        if cmd == "score":
            s = metrics.latest()
            v = s["score"]
            bar = "█" * (v // 5) + "░" * (20 - v // 5)
            verdict = ("EXCELLENT" if v >= 85 else "GOOD" if v >= 70
                       else "FAIR" if v >= 50 else "DEGRADED")
            return f"[{bar}] {v}/100  {verdict}"
        if cmd == "users":
            n = int(args[0]) if args and args[0].isdigit() else 100
            us = db.list_users()[:n]
            if not us:
                return "no users yet — try: add <name> [gb] [days]"
            lines = [f"{'ID':<4}{'USER':<18}{'USED':>10}  {'QUOTA':>10}  ST"]
            for u in us:
                t = u["used_up"] + u["used_down"]
                qz = _h(u["quota_bytes"]) if u["quota_bytes"] else "∞"
                st = "ON " if u["enabled"] else "OFF"
                lines.append(f"{u['id']:<4}{u['username'][:17]:<18}"
                             f"{_h(t):>10}  {qz:>10}  {st}")
            return "\n".join(lines)
        if cmd == "user" and args:
            u = _find(args[0])
            if not u:
                return f"no such user: {args[0]}"
            r = gamify.rank_for(u["xp"])
            t = u["used_up"] + u["used_down"]
            return (f"#{u['id']} {u['username']}\n"
                    f"  uuid     {u['uuid']}\n"
                    f"  rank     {r['icon']} {r['name']} ({u['xp']} XP)\n"
                    f"  used     {_h(t)}  (↑{_h(u['used_up'])} "
                    f"↓{_h(u['used_down'])})\n"
                    f"  quota    {_h(u['quota_bytes']) if u['quota_bytes'] else '∞'}\n"
                    f"  expires  {_dt(u['expires_at'])}\n"
                    f"  status   {'enabled' if u['enabled'] else 'disabled'}\n"
                    f"  sub      /sub/{u['sub_token']}")
        if cmd == "add" and args:
            name = args[0]
            if not re.fullmatch(r"[A-Za-z0-9_.-]{2,32}", name):
                return "invalid username"
            if db.one("SELECT 1 FROM users WHERE username=?", (name,)):
                return "username already exists"
            gb = float(args[1]) if len(args) > 1 else 0
            days = int(args[2]) if len(args) > 2 else 0
            u = db.create_user(name, gb, days)
            xray.reload()
            return f"created #{u['id']} {u['username']}  sub=/sub/{u['sub_token']}"
        if cmd in ("del", "rm") and args:
            u = _find(args[0])
            if not u:
                return f"no such user: {args[0]}"
            db.delete_user(u["id"])
            xray.reload()
            return f"deleted {u['username']}"
        if cmd in ("enable", "disable") and args:
            u = _find(args[0])
            if not u:
                return f"no such user: {args[0]}"
            db.update_user(u["id"], enabled=1 if cmd == "enable" else 0)
            xray.reload()
            return f"{u['username']} {cmd}d"
        if cmd == "reset" and args:
            u = _find(args[0])
            if not u:
                return f"no such user: {args[0]}"
            nu = db.update_user(u["id"], uuid=db.new_uuid(),
                                trojan_pass=db.new_token(16),
                                ss_pass=db.new_token(16),
                                sub_token=db.new_token(20))
            xray.reload()
            return f"rotated {nu['username']}  sub=/sub/{nu['sub_token']}"
        if cmd == "top":
            n = int(args[0]) if args and args[0].isdigit() else 10
            rows = metrics.top_users(n)
            if not rows:
                return "no data"
            return "\n".join(
                f"{i+1:>2}. {r['username'][:20]:<20} {_h(r['total']):>10}  "
                f"{r['rank']['icon']} {r['rank']['name']}"
                for i, r in enumerate(rows))
        if cmd == "events":
            n = int(args[0]) if args and args[0].isdigit() else 15
            rows = db.query("SELECT * FROM events ORDER BY ts DESC LIMIT ?", (n,))
            if not rows:
                return "no events"
            return "\n".join(
                f"{_dt(r['ts'])}  [{r['level'][:4]:<4}] {r['message']}"
                for r in rows)
        if cmd == "turbo":
            if args and args[0] in ("on", "off"):
                db.set_setting("turbo_mode", args[0] == "on")
                ok, msg = xray.reload()
                return (f"turbo {args[0]} — "
                        f"{'applied' if ok else 'reload failed: ' + msg}")
            return f"turbo is {'on' if db.get_setting('turbo_mode') else 'off'}"
        if cmd == "reload":
            ok, msg = xray.reload()
            return "xray reloaded" if ok else f"reload failed: {msg}"
        if cmd == "paths":
            return "\n".join(f"  {k:<9} {v}" for k, v in paths.ALL.items())
        if cmd == "uptime":
            return metrics.latest().get("uptime", "?")
        return f"unknown command: {cmd}  (try 'help')"

    # ── SSE ──────────────────────────────────────────────────────────────
    def stream(self):
        if not auth.verify(self.token()):
            return self.err(401, "unauthorized")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-transform")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        q = metrics.subscribe()
        try:
            self.wfile.write(
                f"data: {json.dumps(metrics.latest())}\n\n".encode())
            self.wfile.flush()
            last_ping = time.time()
            while True:
                try:
                    snap = q.get(timeout=5)
                    self.wfile.write(f"data: {json.dumps(snap)}\n\n".encode())
                    self.wfile.flush()
                except queue.Empty:
                    if time.time() - last_ping > 15:
                        self.wfile.write(b": keepalive\n\n")
                        self.wfile.flush()
                        last_ping = time.time()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            metrics.unsubscribe(q)

    # ── WebSocket echo (tunnel latency measurement) ────────────────────
    def ws_echo(self):
        """RFC 6455 echo endpoint: one frame in, the same frame back.

        Deliberately minimal (no extensions, no fragmentation, no
        compression): a game client times round trips through the REAL
        tunnel path — TLS, Cloudflare, nginx — instead of a short-lived
        HTTP request.
        """
        key = self.headers.get("Sec-WebSocket-Key", "")
        if not key:
            return self.err(400, "websocket handshake required")
        accept = base64.b64encode(hashlib.sha1(
            (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()
        ).digest()).decode()
        self.send_response(101)
        self.send_header("Upgrade", "websocket")
        self.send_header("Connection", "Upgrade")
        self.send_header("Sec-WebSocket-Accept", accept)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        # The socket is now a WebSocket, not HTTP keep-alive; the server
        # must not try to parse further HTTP requests on it.
        self.close_connection = True
        try:
            self.wfile.flush()
            self._ws_loop()
        except Exception:
            pass

    def _ws_loop(self):
        r, w = self.rfile, self.wfile
        # Idle tunnels are closed after 5 minutes; the client reconnects.
        self.connection.settimeout(300)
        try:
            while True:
                hdr = r.read(2)
                if not hdr or len(hdr) < 2:
                    break
                op = hdr[0] & 0x0F
                masked = bool(hdr[1] & 0x80)
                ln = hdr[1] & 0x7F
                if ln == 126:
                    b = r.read(2)
                    if len(b) < 2:
                        break
                    ln = struct.unpack(">H", b)[0]
                elif ln == 127:
                    b = r.read(8)
                    if len(b) < 8:
                        break
                    ln = struct.unpack(">Q", b)[0]
                if ln > (1 << 20):          # refuse oversized frames
                    break
                mask = r.read(4) if masked else b""
                if masked and len(mask) < 4:
                    break
                payload = r.read(ln) if ln else b""
                if len(payload) < ln:
                    break
                if masked:
                    payload = bytes(b ^ mask[i & 3] for i, b in
                                    enumerate(payload))
                if op == 0x8:               # close
                    w.write(b"\x88\x00")
                    w.flush()
                    break
                elif op == 0x9:             # ping -> pong
                    w.write(bytes([0x8A]) + _ws_len(len(payload)) + payload)
                    w.flush()
                elif op in (0x0, 0x1, 0x2):  # continuation/text/binary echo
                    w.write(bytes([0x80 | op]) + _ws_len(len(payload))
                            + payload)
                    w.flush()
        except Exception:
            pass
        finally:
            try:
                self.connection.close()
            except Exception:
                pass


# ── small helpers ────────────────────────────────────────────────────────────

def _ws_len(n: int) -> bytes:
    """WebSocket frame length prefix for an unmasked server frame."""
    if n < 126:
        return bytes([n])
    if n < 65536:
        return bytes([126]) + struct.pack(">H", n)
    return bytes([127]) + struct.pack(">Q", n)


def _version() -> str:
    from . import __version__
    return __version__


def _h(n) -> str:
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unit == "TB":
            return f"{n:.1f}{unit}" if unit != "B" else f"{int(n)}B"
        n /= 1024
    return f"{n:.1f}TB"


def _dt(ts) -> str:
    ts = int(ts or 0)
    if not ts:
        return "never"
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))


def _is_public_host(h: str) -> bool:
    """
    Reject anything a client outside the server could not dial.

    Loopback, link-local and RFC 1918 addresses, plus bare names with no dot,
    all produce configs that can never connect, so they must never reach a
    subscription.
    """
    if not h or len(h) > 253:
        return False
    if not re.fullmatch(r"[a-z0-9.\-]+", h):
        return False
    if h in ("localhost", "localhost.localdomain"):
        return False
    # Looks like an IPv4 literal?
    parts = h.split(".")
    if len(parts) == 4 and all(p.isdigit() for p in parts):
        try:
            a, b = int(parts[0]), int(parts[1])
        except ValueError:
            return False
        if a == 127 or a == 0 or a == 10:
            return False
        if a == 172 and 16 <= b <= 31:
            return False
        if a == 192 and b == 168:
            return False
        if a == 169 and b == 254:
            return False
        return True
    # Hostnames must be dotted; a single label is never publicly resolvable.
    return "." in h


def _clean_kinds(v) -> str:
    """
    Normalise a transport selection into the stored comma-separated form.

    Accepts a list (what the panel sends) or a string (what a hand-written
    API call is likely to send). Unknown kinds are discarded rather than
    rejected, so a client built against a future version cannot store a
    value that later empties someone's subscription.
    """
    if isinstance(v, (list, tuple)):
        v = ",".join(str(x) for x in v)
    return ",".join(links.parse_kinds(_as_str(v)))


def _as_str(v) -> str:
    """Coerce any JSON scalar to a string. Never raises."""
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    return ""


def _as_name(v) -> str:
    return _as_str(v).strip()


def _as_float(v, default: float = 0.0) -> float:
    """Tolerant float parse — clients send strings, nulls and junk."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    if f != f or f in (float("inf"), float("-inf")):   # NaN / inf
        return default
    return max(0.0, min(f, 1e9))


def _as_int(v, default: int = 0) -> int:
    try:
        return max(0, min(int(float(v)), 10 ** 9))
    except (TypeError, ValueError):
        return default


def _find(key: str) -> dict | None:
    if key.isdigit():
        u = db.get_user(int(key))
        if u:
            return u
    r = db.one("SELECT * FROM users WHERE username=?", (key,))
    return dict(r) if r else None


class _Server(ThreadingHTTPServer):
    """Threading server tuned for bursts of concurrent panel requests."""
    daemon_threads = True
    allow_reuse_address = True
    # Default is 5, which drops connections when the panel fires a burst of
    # parallel XHRs (or several admins act at once).
    request_queue_size = 128

    def server_bind(self):
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self.socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            pass
        super().server_bind()

    def handle_error(self, request, client_address):
        """Client disconnects are normal (SSE, aborted fetches) — stay quiet."""
        import sys
        exc = sys.exc_info()[1]
        if isinstance(exc, (BrokenPipeError, ConnectionResetError,
                            ConnectionAbortedError, TimeoutError)):
            return
        super().handle_error(request, client_address)


def serve() -> None:
    httpd = _Server(BIND, Handler)
    httpd.serve_forever()
