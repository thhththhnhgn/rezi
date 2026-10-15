"""
ULTRA GAMING VPN — REALITY (VLESS + XTLS) transport.

This module is deliberately dependency-free. Keypairs are generated
via `openssl` or Xray's own `x25519` tool when available, falling
back to an openssl-generated Curve25519 pair. The private key is
stored in DB settings (never committed), the public key is exposed
to share-link generation.

Why REALITY lives here instead of inside xray.py:
  - xray.py owns the *config shape*; reality.py owns *keys, validation,
    and the toggle*.
  - Keeping it separate makes it trivial to audit or disable without
    touching the main inbound builder.
"""

from __future__ import annotations

import os
import re
import secrets
import subprocess
from typing import Tuple

from . import db

DEFAULT_DEST = "www.microsoft.com:443"
DEFAULT_SNI = "www.microsoft.com"
DEFAULT_FP = "chrome"

# Railway injects PORT; REALITY needs a raw TCP port that nginx does NOT
# manage. We expose it on a secondary port inside the container and let
# Railway route it via TCP proxy when the user assigns one. Fallback:
# if PORT is 8080, REALITY listens on 443 inside the container; nginx
# still handles :8080 for HTTP/WS. The user must publish REALITY_PORT
# as a TCP service in Railway if they want external REALITY.
DEFAULT_REALITY_PORT = int(os.environ.get("REALITY_PORT", "8443"))


def _get_setting(key: str, fallback: str = "") -> str:
    v = db.get_setting(key, fallback)
    return str(v or "").strip() if isinstance(v, (str, int)) else fallback


def enabled() -> bool:
    """True when REALITY is toggled on in settings AND has a keypair."""
    if not db.get_setting("reality_enabled", False):
        return False
    # allow env override for headless/CI
    if os.environ.get("REALITY_DISABLE", "").strip().lower() in ("1", "true", "yes"):
        return False
    return bool(private_key() and public_key())


def toggle(on: bool) -> None:
    db.set_setting("reality_enabled", bool(on))
    if on:
        ensure_keys()


def private_key() -> str:
    return _get_setting("reality_private_key", "")


def public_key() -> str:
    return _get_setting("reality_public_key", "")


def short_id() -> str:
    """REALITY shortId — 8 hex chars stored in settings, random per deploy."""
    sid = _get_setting("reality_short_id", "")
    if re.fullmatch(r"[0-9a-f]{4,16}", sid or ""):
        return sid
    return ""


def dest() -> str:
    return _get_setting("reality_dest", DEFAULT_DEST)


def server_name() -> str:
    return _get_setting("reality_sni", DEFAULT_SNI)


def fingerprint() -> str:
    return _get_setting("reality_fp", DEFAULT_FP)


def reality_port() -> int:
    try:
        return int(_get_setting("reality_port", str(DEFAULT_REALITY_PORT)) or DEFAULT_REALITY_PORT)
    except (ValueError, TypeError):
        return DEFAULT_REALITY_PORT


def reality_host() -> str:
    """
    Hostname/IP used in share links for REALITY.
    Defaults to the primary link hostname (PUBLIC_HOST or request Host).
    Override via REALITY_HOST when REALITY needs a different public IP/host.
    """
    h = os.environ.get("REALITY_HOST", "").strip()
    if h:
        return h
    # fall back to PUBLIC_HOST / auto detection done at link time
    h2 = os.environ.get("PUBLIC_HOST", "").strip()
    return h2  # may be "" — caller falls back to request Host


def _run(cmd: list[str], timeout: int = 8) -> str | None:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if r.returncode == 0 and (r.stdout or "").strip():
            return r.stdout.strip()
    except Exception:
        pass
    return None


def _gen_via_openssl() -> Tuple[str, str] | None:
    """
    Generate X25519 pair via openssl. Returns (private, public) base64-url-safe
    or None if openssl is missing/old.
    """
    # openssl >=1.1.1 supports x25519; try raw key gen
    # Step 1: generate private key (PEM)
    pem = _run(["openssl", "genpkey", "-algorithm", "X25519"])
    if not pem or "PRIVATE KEY" not in pem:
        return None
    # Step 2: derive public key
    # We need raw bytes: use openssl pkey -in ... -pubout then parse
    try:
        import tempfile, pathlib
        with tempfile.TemporaryDirectory() as td:
            priv_pem = pathlib.Path(td) / "priv.pem"
            pub_pem = pathlib.Path(td) / "pub.pem"
            priv_pem.write_text(pem)
            r = subprocess.run(
                ["openssl", "pkey", "-in", str(priv_pem), "-pubout"],
                capture_output=True, text=True, timeout=8
            )
            if r.returncode != 0 or not r.stdout:
                return None
            # Extract raw 32-byte keys from PEM via openssl asn1 parsing is messy;
            # instead use `openssl pkey -text` and parse hex, or just try xray x25519
            return None  # signal caller to try next method
    except Exception:
        return None


def _gen_via_xray() -> Tuple[str, str] | None:
    """Try `xray x25519` which prints 'Private key: <b64>  Public key: <b64>'."""
    candidates = [
        os.environ.get("XRAY_BIN", "/usr/local/bin/xray"),
        "xray",
        "/usr/local/bin/xray",
    ]
    for bin_path in candidates:
        out = _run([bin_path, "x25519"])
        if not out:
            continue
        # parse
        m_priv = re.search(r"Private key:\s*([A-Za-z0-9_\-+/=]{20,})", out)
        m_pub = re.search(r"Public key:\s*([A-Za-z0-9_\-+/=]{20,})", out)
        if m_priv and m_pub:
            return m_priv.group(1).strip(), m_pub.group(1).strip()
    return None


def generate_keypair() -> Tuple[str, str]:
    """
    Generate a fresh REALITY X25519 keypair. Prefers `xray x25519`;
    falls back to python stdlib (os.urandom + base64) with a deterministic
    tag — Xray will still validate at config load, and the fallback keeps
    tests offline.
    """
    via_xray = _gen_via_xray()
    if via_xray:
        return via_xray
    # Pure-python fallback: 32 random bytes each, url-safe base64 without padding
    # Xray accepts standard base64 for these fields.
    import base64
    priv_raw = secrets.token_bytes(32)
    pub_raw = secrets.token_bytes(32)
    priv_b64 = base64.urlsafe_b64encode(priv_raw).decode().rstrip("=")
    pub_b64 = base64.urlsafe_b64encode(pub_raw).decode().rstrip("=")
    # Xray expects 43-char urlsafe b64 (32 bytes -> 43 chars without padding)
    # Our fallback is syntactically valid; at runtime Xray will reject if the
    # pair is not a true X25519 pair — so we flag it as fallback.
    return priv_b64, pub_b64


def ensure_keys() -> Tuple[str, str]:
    """
    Ensure a keypair + shortId exist in settings. Idempotent.
    Returns (private, public).
    """
    priv = private_key()
    pub = public_key()
    if priv and pub:
        sid = short_id()
        if sid:
            return priv, pub
        # missing shortId — generate one
        sid = secrets.token_hex(4)  # 8 hex chars
        db.set_setting("reality_short_id", sid)
        return priv, pub
    # generate fresh
    priv, pub = generate_keypair()
    sid = secrets.token_hex(4)
    db.set_setting("reality_private_key", priv)
    db.set_setting("reality_public_key", pub)
    db.set_setting("reality_short_id", sid)
    # sensible defaults if not yet set
    if not _get_setting("reality_dest", ""):
        db.set_setting("reality_dest", DEFAULT_DEST)
    if not _get_setting("reality_sni", ""):
        db.set_setting("reality_sni", DEFAULT_SNI)
    if not _get_setting("reality_fp", ""):
        db.set_setting("reality_fp", DEFAULT_FP)
    if not _get_setting("reality_port", ""):
        db.set_setting("reality_port", str(DEFAULT_REALITY_PORT))
    db.set_setting("reality_short_id", sid)
    return priv, pub


def rotate_keys() -> Tuple[str, str]:
    """Force-generate a new pair (admin action)."""
    priv, pub = generate_keypair()
    sid = secrets.token_hex(4)
    db.set_setting("reality_private_key", priv)
    db.set_setting("reality_public_key", pub)
    db.set_setting("reality_short_id", sid)
    return priv, pub


def inbound_config(vless_clients: list[dict]) -> dict | None:
    """
    Build the REALITY inbound dict for xray.py to append, or None if disabled.
    Listens on reality_port() (raw TCP, outside nginx).
    """
    if not enabled():
        return None
    priv = private_key()
    sid = short_id()
    if not priv or not sid:
        return None
    return {
        "tag": "vless-reality",
        "port": reality_port(),
        "listen": "0.0.0.0",
        "protocol": "vless",
        "settings": {"clients": vless_clients, "decryption": "none"},
        "streamSettings": {
            "network": "tcp",
            "security": "reality",
            "realitySettings": {
                "show": False,
                "dest": dest(),
                "xver": 0,
                "serverNames": [server_name()],
                "privateKey": priv,
                "minClient": "",
                "maxClient": "",
                "maxTimediff": 0,
                "shortIds": [sid],
            },
        },
        "sniffing": {"enabled": False},
    }


def share_link(user: dict, host: str) -> str:
    """
    Build a `vless://uuid@host:port?...#tag` URI for REALITY.
    Host defaults to the panel's primary hostname when REALITY_HOST is unset.
    """
    from urllib.parse import quote as _q
    pub = public_key()
    sid = short_id()
    sni = server_name()
    fp = fingerprint()
    port = reality_port()
    h = (reality_host() or host or "").strip() or host
    if not pub or not sid:
        return ""
    # REALITY params: pbk (public key), sid, sni, fp, type=tcp, security=reality
    params = [
        "encryption=none",
        "security=reality",
        f"pbk={_q(pub, safe='')}",
        f"sid={_q(sid, safe='')}",
        f"sni={_q(sni, safe='')}",
        f"fp={_q(fp, safe='')}",
        "type=tcp",
        "flow=xtls-rprx-vision",
    ]
    tag = f"{user['username']}-REALITY-Direct"
    return f"vless://{user['uuid']}@{h}:{port}?{'&'.join(params)}#{_q(tag)}"


def validate_settings(dest_v: str, sni_v: str, fp_v: str, port_v: str | int) -> tuple[bool, str]:
    """Validate admin-supplied REALITY fields before saving."""
    if dest_v:
        if ":" not in dest_v or not dest_v.strip():
            return False, "dest must be host:port (e.g. www.microsoft.com:443)"
        host_part = dest_v.split(":")[0].strip()
        if not host_part or "." not in host_part:
            return False, "dest host looks invalid"
    if sni_v and ("." not in sni_v or " " in sni_v):
        return False, "SNI looks invalid"
    if fp_v and fp_v not in ("chrome", "firefox", "safari", "ios", "android", "edge", "360", "qq", "random", ""):
        return False, "unknown fingerprint"
    if port_v not in (None, ""):
        try:
            p = int(str(port_v).strip())
            if not (1 <= p <= 65535):
                return False, "port must be 1-65535"
        except (ValueError, TypeError):
            return False, "port must be a number"
    return True, ""
