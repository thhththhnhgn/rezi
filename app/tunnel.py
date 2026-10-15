"""
ULTRA GAMING VPN — Cloudflare Tunnel helper.

The tunnel hostname (xxx.trycloudflare.com or a named tunnel) is discovered
by start.sh and written to /tmp/tunnel_host. This module exposes it to the
control plane so every subscription automatically gains an extra host.

No extra dependencies, no blocking I/O at import time.
"""

from __future__ import annotations

import os
import re

_FILE = os.environ.get("TUNNEL_FILE", "/tmp/tunnel_host")


def _clean_host(raw: str) -> str:
    h = (raw or "").strip().lower()
    # strip scheme / path / port
    h = h.split("://")[-1].split("/")[0].split(":")[0]
    return h


def _is_public_host(h: str) -> bool:
    if not h or len(h) > 253:
        return False
    if not re.fullmatch(r"[a-z0-9.\-]+", h):
        return False
    if h in ("localhost", "localhost.localdomain"):
        return False
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
    return "." in h


def get_tunnel_host() -> str | None:
    """
    Return the tunnel hostname if available, else None.

    Priority:
      1. TUNNEL_HOST env (explicit, for named tunnels or manual override)
      2. File written by start.sh (/tmp/tunnel_host) — quick tunnel case
    Returns a clean, public hostname or None.
    """
    # Explicit env wins — lets an operator pin a named tunnel hostname
    # without waiting for the file, or override the quick-tunnel one.
    env_raw = os.environ.get("TUNNEL_HOST", "")
    if env_raw.strip():
        h = _clean_host(env_raw)
        if _is_public_host(h):
            return h

    # File from start.sh (quick tunnel)
    try:
        with open(_FILE, encoding="utf-8") as f:
            raw = f.read().strip()
            if raw:
                h = _clean_host(raw)
                if _is_public_host(h):
                    return h
    except (OSError, UnicodeDecodeError):
        pass

    return None


def is_available() -> bool:
    """True if a tunnel hostname is currently known."""
    return get_tunnel_host() is not None
