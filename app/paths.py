"""
ULTRA GAMING VPN — obfuscated transport paths.

Every proxy endpoint lives under a secret prefix derived from PATH_SECRET.
Scanners hitting /vless, /vmess, /ws ... get the decoy site instead, so the
deployment does not look like a proxy from the outside.

Set PATH_SECRET in Railway to rotate every path at once.
Set PATH_PREFIX to pin a human-readable prefix instead of the derived one.
"""

from __future__ import annotations

import hashlib
import os

_SECRET = os.environ.get("PATH_SECRET", "").strip()
_PINNED = os.environ.get("PATH_PREFIX", "").strip().strip("/")


def _h(*parts: str, n: int = 10) -> str:
    seed = "|".join((_SECRET,) + parts).encode()
    return hashlib.sha256(seed).hexdigest()[:n]


# Public prefix for all tunnel endpoints, e.g. "/x7f3a9c2b1d"
if _PINNED:
    PREFIX = "/" + _PINNED
elif _SECRET:
    PREFIX = "/" + _h("prefix", n=12)
else:
    # No secret configured -> keep the classic, predictable paths so that
    # an existing deployment does not break on upgrade.
    PREFIX = ""

P_XHTTP = f"{PREFIX}/xhttp"
P_VLESS = f"{PREFIX}/vless"
P_VMESS = f"{PREFIX}/vmess"
P_TROJAN = f"{PREFIX}/trojan"
P_UPGRADE = f"{PREFIX}/upgrade"
P_PING = f"{PREFIX}/echo"          # latency probe websocket

ALL = {
    "xhttp": P_XHTTP,
    "vless": P_VLESS,
    "vmess": P_VMESS,
    "trojan": P_TROJAN,
    "upgrade": P_UPGRADE,
}

# nginx needs the prefix at build time; expose a plain string for templating.
NGINX_PREFIX = PREFIX or ""
