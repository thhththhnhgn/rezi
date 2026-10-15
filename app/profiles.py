"""
ULTRA GAMING VPN — per-game tuning profiles and game-server ping targets.

Profiles express *client-side* transport hints baked into generated share
links / sing-box output: mux, fragmentation, keepalive and which transport
is offered first. They do not change the server config (that is global via
turbo_mode), they change how the client behaves.

GAME_SERVERS lists public endpoints close to each title's real datacentres,
used by the panel's "ping to game servers" test. Every entry must be
reachable over plain HTTPS from a browser, because the probe runs in the
user's browser (a server-side probe would measure the wrong path).
"""

from __future__ import annotations

GAME_PROFILES: dict[str, dict] = {
    "balanced": {
        "label": "Balanced",
        "icon": "⚖️",
        "desc": "Everyday browsing + casual play. Safe defaults.",
        "color": "#00ffc8",
        "mux": {"enabled": True, "concurrency": 4, "xudp": 8,
                "xudp_udp443": "reject"},
        "fragment": None,
        "keepalive": 30,
        "prefer": "httpupgrade",
        "tags": ["default"],
    },
    "valorant": {
        "label": "Valorant / CS2",
        "icon": "🎯",
        "desc": "Tac-shooters. Mux off, zero buffering, tick-accurate.",
        "color": "#ff4757",
        "mux": {"enabled": True, "concurrency": 4, "xudp": 16,
                "xudp_udp443": "reject"},
        "fragment": None,
        "keepalive": 15,
        "prefer": "httpupgrade",
        "tags": ["fps", "low-latency"],
    },
    "pubg": {
        "label": "PUBG / COD Mobile",
        "icon": "🔫",
        "desc": "Mobile battle royale. Tuned for flaky cellular links.",
        "color": "#ffa502",
        "mux": {"enabled": True, "concurrency": 4, "xudp": 16,
                "xudp_udp443": "reject"},
        "fragment": None,
        "keepalive": 15,
        "prefer": "httpupgrade",
        "tags": ["mobile", "br"],
    },
    "fortnite": {
        "label": "Fortnite / Apex",
        "icon": "🏹",
        "desc": "Fast-paced BR with heavy asset streaming.",
        "color": "#8b5cf6",
        "mux": {"enabled": True, "concurrency": 4, "xudp": 16,
                "xudp_udp443": "reject"},
        "fragment": None,
        "keepalive": 25,
        "prefer": "httpupgrade",
        "tags": ["br"],
    },
    "moba": {
        "label": "LoL / Dota / Wild Rift",
        "icon": "🛡️",
        "desc": "MOBA. Stable long sessions, jitter-averse.",
        "color": "#3742fa",
        "mux": {"enabled": True, "concurrency": 4, "xudp": 16,
                "xudp_udp443": "reject"},
        "fragment": None,
        "keepalive": 20,
        "prefer": "httpupgrade",
        "tags": ["moba"],
    },
    "fcmobile": {
        "label": "FC Mobile / eFootball",
        "icon": "⚽",
        "desc": "Football sims. Rock-steady jitter matters more than raw ping.",
        "color": "#2ed573",
        "mux": {"enabled": True, "concurrency": 4, "xudp": 16,
                "xudp_udp443": "reject"},
        "fragment": None,
        "keepalive": 15,
        "prefer": "httpupgrade",
        "tags": ["sports", "mobile", "low-latency"],
    },
    "clashroyale": {
        "label": "Clash Royale / CoC",
        "icon": "👑",
        "desc": "Supercell titles. Tiny packets, long idle sessions.",
        "color": "#ffd32a",
        "mux": {"enabled": True, "concurrency": 4, "xudp": 8,
                "xudp_udp443": "reject"},
        "fragment": None,
        "keepalive": 45,
        "prefer": "httpupgrade",
        "tags": ["mobile", "strategy"],
    },
    "brawlstars": {
        "label": "Brawl Stars",
        "icon": "💥",
        "desc": "Fast 3v3. Mux off so a stall never blocks another stream.",
        "color": "#ff6b81",
        "mux": {"enabled": True, "concurrency": 4, "xudp": 16,
                "xudp_udp443": "reject"},
        "fragment": None,
        "keepalive": 15,
        "prefer": "httpupgrade",
        "tags": ["mobile", "arena", "low-latency"],
    },
    "stealth": {
        "label": "Stealth Mode",
        "icon": "🥷",
        "desc": "Maximum DPI evasion. Slower, but gets through.",
        "color": "#a4b0be",
        "mux": {"enabled": True, "concurrency": 8, "xudp": 8,
                "xudp_udp443": "reject"},
        "fragment": {"packets": "tlshello", "length": "10-30", "interval": "20-40"},
        "keepalive": 45,
        "prefer": "httpupgrade",
        "tags": ["bypass"],
    },
    "streaming": {
        "label": "Streaming / Download",
        "icon": "📺",
        "desc": "Throughput first. Big buffers, high concurrency.",
        "color": "#2ed573",
        "mux": {"enabled": True, "concurrency": 32, "xudp": 16,
                "xudp_udp443": "allow"},
        "fragment": None,
        "keepalive": 60,
        "prefer": "xhttp",
        "tags": ["throughput"],
    },
}

DEFAULT_PROFILE = "balanced"


# ── game server ping targets ────────────────────────────────────────────────
GAME_SERVERS: list[dict] = [
    {
        "id": "valorant",
        "name": "Valorant",
        "icon": "🎯",
        "color": "#ff4757",
        "regions": [
            {"id": "eu-frankfurt", "label": "Frankfurt", "flag": "🇩🇪",
             "url": "https://eu.api.riotgames.com/riot/account/v1/accounts/me"},
            {"id": "eu-london", "label": "London", "flag": "🇬🇧",
             "url": "https://euw1.api.riotgames.com/lol/status/v4/platform-data"},
            {"id": "me-bahrain", "label": "Bahrain", "flag": "🇧🇭",
             "url": "https://me1.api.riotgames.com/lol/status/v4/platform-data"},
            {"id": "tr-istanbul", "label": "Istanbul", "flag": "🇹🇷",
             "url": "https://tr1.api.riotgames.com/lol/status/v4/platform-data"},
        ],
    },
    {
        "id": "cs2",
        "name": "CS2 / Steam",
        "icon": "🔫",
        "color": "#ffa502",
        "regions": [
            {"id": "steam-eu", "label": "Europe", "flag": "🇪🇺",
             "url": "https://api.steampowered.com/ISteamWebAPIUtil/GetServerInfo/v1/"},
            {"id": "steam-cdn", "label": "Steam CDN", "flag": "🌍",
             "url": "https://cdn.fastly.steamstatic.com/steam/apps/730/header.jpg"},
        ],
    },
    {
        "id": "fcmobile",
        "name": "FC Mobile (EA)",
        "icon": "⚽",
        "color": "#2ed573",
        "regions": [
            {"id": "ea-global", "label": "EA Global", "flag": "🌍",
             "url": "https://www.ea.com/favicon.ico"},
            {"id": "ea-cdn", "label": "EA CDN", "flag": "🌐",
             "url": "https://media.contentapi.ea.com/content/dam/eacom/common/favicon.ico"},
        ],
    },
    {
        "id": "efootball",
        "name": "eFootball (PES)",
        "icon": "🥅",
        "color": "#00d4ff",
        "regions": [
            {"id": "konami-global", "label": "Konami Global", "flag": "🌍",
             "url": "https://www.konami.com/efootball/favicon.ico"},
            {"id": "konami-jp", "label": "Konami JP", "flag": "🇯🇵",
             "url": "https://www.konami.com/favicon.ico"},
        ],
    },
    {
        "id": "supercell",
        "name": "Clash Royale / CoC",
        "icon": "👑",
        "color": "#ffd32a",
        "regions": [
            {"id": "sc-api", "label": "Supercell API", "flag": "🇫🇮",
             "url": "https://api.clashroyale.com/v1/cards"},
            {"id": "sc-coc", "label": "Clash of Clans", "flag": "🇫🇮",
             "url": "https://api.clashofclans.com/v1/locations"},
            {"id": "sc-site", "label": "Supercell", "flag": "🌍",
             "url": "https://supercell.com/favicon.ico"},
        ],
    },
    {
        "id": "brawlstars",
        "name": "Brawl Stars",
        "icon": "💥",
        "color": "#ff6b81",
        "regions": [
            {"id": "bs-api", "label": "Brawl API", "flag": "🇫🇮",
             "url": "https://api.brawlstars.com/v1/brawlers"},
            {"id": "bs-site", "label": "Brawl Stars", "flag": "🌍",
             "url": "https://brawlstars.com/favicon.ico"},
        ],
    },
    {
        "id": "pubgm",
        "name": "PUBG Mobile",
        "icon": "🪖",
        "color": "#f39c12",
        "regions": [
            {"id": "pubg-global", "label": "PUBG Global", "flag": "🌍",
             "url": "https://www.pubgmobile.com/favicon.ico"},
            {"id": "tencent", "label": "Tencent", "flag": "🇸🇬",
             "url": "https://www.tencentgames.com/favicon.ico"},
        ],
    },
    {
        "id": "fortnite",
        "name": "Fortnite / Epic",
        "icon": "🏹",
        "color": "#8b5cf6",
        "regions": [
            {"id": "epic-global", "label": "Epic Global", "flag": "🌍",
             "url": "https://www.epicgames.com/favicon.ico"},
            {"id": "epic-cdn", "label": "Epic CDN", "flag": "🌐",
             "url": "https://cdn2.unrealengine.com/favicon.ico"},
        ],
    },
    {
        "id": "codm",
        "name": "COD Mobile",
        "icon": "🎖️",
        "color": "#e67e22",
        "regions": [
            {"id": "activision", "label": "Activision", "flag": "🌍",
             "url": "https://www.callofduty.com/favicon.ico"},
        ],
    },
    {
        "id": "mobilelegends",
        "name": "Mobile Legends",
        "icon": "🛡️",
        "color": "#3742fa",
        "regions": [
            {"id": "ml-global", "label": "Moonton", "flag": "🇸🇬",
             "url": "https://www.mobilelegends.com/favicon.ico"},
        ],
    },
    {
        "id": "roblox",
        "name": "Roblox",
        "icon": "🧱",
        "color": "#e74c3c",
        "regions": [
            {"id": "rbx-global", "label": "Roblox", "flag": "🌍",
             "url": "https://www.roblox.com/favicon.ico"},
        ],
    },
    {
        "id": "minecraft",
        "name": "Minecraft",
        "icon": "⛏️",
        "color": "#27ae60",
        "regions": [
            {"id": "mc-global", "label": "Mojang", "flag": "🌍",
             "url": "https://www.minecraft.net/favicon.ico"},
        ],
    },
]


def get(name: str | None) -> dict:
    return GAME_PROFILES.get((name or "").lower(), GAME_PROFILES[DEFAULT_PROFILE])


def listing() -> list[dict]:
    return [{"id": k, **v} for k, v in GAME_PROFILES.items()]


def games() -> list[dict]:
    return GAME_SERVERS
