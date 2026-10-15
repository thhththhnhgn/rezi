"""
ULTRA GAMING VPN — ranks, XP and achievements.

XP is earned from traffic (1 XP per 100 MB) and from uptime days.
Ranks follow a familiar tac-shooter ladder so the panel feels like a game.
"""

from __future__ import annotations

import time

from . import db

RANKS = [
    ("Iron",      0,      "#8d8d8d", "🔩"),
    ("Bronze",    100,    "#cd7f32", "🥉"),
    ("Silver",    400,    "#c0c0c0", "🥈"),
    ("Gold",      1000,   "#ffd700", "🥇"),
    ("Platinum",  2200,   "#40e0d0", "💠"),
    ("Diamond",   4500,   "#5eead4", "💎"),
    ("Ascendant", 8000,   "#22c55e", "🌿"),
    ("Immortal",  14000,  "#a855f7", "🔮"),
    ("Radiant",   24000,  "#fde047", "☀️"),
]

ACHIEVEMENTS = {
    "first_blood":   ("First Blood",      "Connected for the first time",      "🩸"),
    "gb_10":         ("Warm Up",          "Used 10 GB of traffic",             "🔥"),
    "gb_100":        ("Century",          "Used 100 GB of traffic",            "💯"),
    "gb_500":        ("Data Hoarder",     "Used 500 GB of traffic",            "🗄️"),
    "gb_1000":       ("Terabyte Club",    "Used 1 TB of traffic",              "🏆"),
    "days_7":        ("Week One",         "Active for 7 days",                 "📅"),
    "days_30":       ("Veteran",          "Active for 30 days",                "🎖️"),
    "days_100":      ("Centurion",        "Active for 100 days",               "🛡️"),
    "night_owl":     ("Night Owl",        "Connected between 2AM and 5AM",     "🦉"),
    "speed_demon":   ("Speed Demon",      "Peaked above 10 MB/s",              "⚡"),
    "rank_gold":     ("Certified Gold",   "Reached Gold rank",                 "🥇"),
    "rank_radiant":  ("Radiant",          "Reached the highest rank",          "☀️"),
}


def rank_for(xp: int) -> dict:
    cur = RANKS[0]
    nxt = None
    for i, r in enumerate(RANKS):
        if xp >= r[1]:
            cur = r
            nxt = RANKS[i + 1] if i + 1 < len(RANKS) else None
        else:
            break
    floor = cur[1]
    ceil = nxt[1] if nxt else max(cur[1] * 2, cur[1] + 1)
    pct = 100.0 if not nxt else round((xp - floor) / max(ceil - floor, 1) * 100, 1)
    return {
        "name": cur[0], "color": cur[2], "icon": cur[3],
        "xp": xp, "floor": floor, "ceil": ceil if nxt else None,
        "next": nxt[0] if nxt else None,
        "progress": max(0.0, min(100.0, pct)),
    }


def xp_for(user: dict) -> int:
    total = int(user.get("used_up", 0)) + int(user.get("used_down", 0))
    traffic_xp = total // (100 * 1024 ** 2)          # 1 XP / 100 MB
    created = int(user.get("created_at") or 0)
    days = max(0, (int(time.time()) - created) // 86400) if created else 0
    return int(traffic_xp + days * 5)


def unlocked(uid: int) -> list[str]:
    return [r["code"] for r in
            db.query("SELECT code FROM achievements WHERE user_id=?", (uid,))]


def grant(uid: int, code: str) -> bool:
    if code not in ACHIEVEMENTS:
        return False
    existing = db.one(
        "SELECT 1 FROM achievements WHERE user_id=? AND code=?", (uid, code))
    if existing:
        return False
    db.execute("INSERT INTO achievements(user_id,code,ts) VALUES(?,?,?)",
               (uid, code, int(time.time())))
    title = ACHIEVEMENTS[code][0]
    db.log_event(f"Achievement unlocked: {title}", kind="achievement",
                 meta={"user_id": uid, "code": code})
    return True


def evaluate(user: dict, peak_speed_bps: float = 0.0) -> list[str]:
    """Grant any achievements the user now qualifies for. Returns new codes."""
    uid = user["id"]
    new: list[str] = []
    total = int(user.get("used_up", 0)) + int(user.get("used_down", 0))
    gb = total / 1024 ** 3
    created = int(user.get("created_at") or 0)
    days = (int(time.time()) - created) / 86400 if created else 0

    checks = [
        ("first_blood", int(user.get("last_seen") or 0) > 0),
        ("gb_10", gb >= 10),
        ("gb_100", gb >= 100),
        ("gb_500", gb >= 500),
        ("gb_1000", gb >= 1000),
        ("days_7", days >= 7),
        ("days_30", days >= 30),
        ("days_100", days >= 100),
        ("speed_demon", peak_speed_bps >= 10 * 1024 ** 2),
    ]
    r = rank_for(xp_for(user))
    checks.append(("rank_gold", r["name"] in
                   ("Gold", "Platinum", "Diamond", "Ascendant",
                    "Immortal", "Radiant")))
    checks.append(("rank_radiant", r["name"] == "Radiant"))

    hour = time.localtime().tm_hour
    if 2 <= hour < 5 and int(user.get("last_seen") or 0) > time.time() - 300:
        checks.append(("night_owl", True))

    for code, ok in checks:
        if ok and grant(uid, code):
            new.append(code)
    return new


def summary(uid: int) -> dict:
    got = set(unlocked(uid))
    return {
        "unlocked": [
            {"code": c, "title": ACHIEVEMENTS[c][0],
             "desc": ACHIEVEMENTS[c][1], "icon": ACHIEVEMENTS[c][2]}
            for c in ACHIEVEMENTS if c in got
        ],
        "locked": [
            {"code": c, "title": ACHIEVEMENTS[c][0],
             "desc": ACHIEVEMENTS[c][1], "icon": ACHIEVEMENTS[c][2]}
            for c in ACHIEVEMENTS if c not in got
        ],
        "total": len(ACHIEVEMENTS),
        "count": len(got),
    }
