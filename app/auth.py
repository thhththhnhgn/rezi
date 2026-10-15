"""
ULTRA GAMING VPN — admin authentication.

Stateless HMAC-signed session tokens (no external JWT dependency),
constant-time password comparison, and brute-force throttling per IP.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import threading
import time

ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASS = os.environ.get("ADMIN_PASS", "")
SECRET = os.environ.get("SECRET_KEY", "")
TTL = int(os.environ.get("SESSION_TTL", "86400"))

if not SECRET:
    # Derived so that tokens stay valid across worker threads within a boot,
    # but a redeploy invalidates them (fine — it's a single-instance panel).
    SECRET = secrets.token_hex(32)

_fails: dict[str, list[float]] = {}
_fail_lock = threading.Lock()
MAX_FAILS = 8
WINDOW = 300


def _b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _sign(payload: bytes) -> str:
    return _b64e(hmac.new(SECRET.encode(), payload, hashlib.sha256).digest())


def issue(subject: str = "admin", scope: str = "admin",
          ttl: int | None = None) -> str:
    body = json.dumps(
        {"sub": subject, "scope": scope,
         "exp": int(time.time()) + (ttl or TTL),
         "jti": secrets.token_hex(6)},
        separators=(",", ":"),
    ).encode()
    return f"{_b64e(body)}.{_sign(body)}"


def verify(token: str | None, scope: str = "admin") -> dict | None:
    if not token or "." not in token:
        return None
    raw, _, sig = token.partition(".")
    try:
        body = _b64d(raw)
    except Exception:
        return None
    if not hmac.compare_digest(_sign(body), sig):
        return None
    try:
        data = json.loads(body)
    except Exception:
        return None
    if int(data.get("exp", 0)) < time.time():
        return None
    if scope and data.get("scope") != scope:
        return None
    return data


def throttled(ip: str) -> bool:
    now = time.time()
    with _fail_lock:
        hits = [t for t in _fails.get(ip, []) if now - t < WINDOW]
        _fails[ip] = hits
        return len(hits) >= MAX_FAILS


def record_fail(ip: str) -> None:
    with _fail_lock:
        _fails.setdefault(ip, []).append(time.time())


def clear_fails(ip: str) -> None:
    with _fail_lock:
        _fails.pop(ip, None)


def check_password(username: str, password: str) -> bool:
    if not ADMIN_PASS:
        return False
    ok_u = hmac.compare_digest(username or "", ADMIN_USER)
    ok_p = hmac.compare_digest(password or "", ADMIN_PASS)
    return ok_u and ok_p


def configured() -> bool:
    return bool(ADMIN_PASS)
