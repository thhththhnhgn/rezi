"""
ULTRA GAMING VPN — Database layer (SQLite, WAL, thread-safe)

Tables
------
users      : VPN accounts (uuid, quota, expiry, rank/XP)
traffic     : per-user cumulative counters + snapshots
metrics     : time-series of system metrics (for 24h/7d/30d charts)
events      : audit log / notifications
achievements: unlocked achievements per user
settings    : key/value runtime settings (turbo mode, decoy, etc.)
"""

from __future__ import annotations

import json
import os
import secrets
import sqlite3
import threading
import time
import uuid as _uuid
from typing import Any

DB_PATH = os.environ.get("DB_PATH", "/data/ultra.db")

_local = threading.local()
_write_lock = threading.Lock()

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT    NOT NULL UNIQUE,
    uuid          TEXT    NOT NULL UNIQUE,
    trojan_pass   TEXT    NOT NULL,
    ss_pass       TEXT    NOT NULL,
    sub_token     TEXT    NOT NULL UNIQUE,
    quota_bytes   INTEGER NOT NULL DEFAULT 0,      -- 0 = unlimited
    used_up       INTEGER NOT NULL DEFAULT 0,
    used_down     INTEGER NOT NULL DEFAULT 0,
    expires_at    INTEGER NOT NULL DEFAULT 0,      -- unix ts, 0 = never
    enabled       INTEGER NOT NULL DEFAULT 1,
    note          TEXT    NOT NULL DEFAULT '',
    -- Comma-separated transport kinds this user's subscription may
    -- contain. Empty means every available config, which is the default
    -- so a user created without an explicit choice behaves as before.
    allowed_kinds TEXT    NOT NULL DEFAULT '',
    xp            INTEGER NOT NULL DEFAULT 0,
    created_at    INTEGER NOT NULL,
    updated_at    INTEGER NOT NULL,
    last_seen     INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS metrics (
    ts        INTEGER PRIMARY KEY,
    cpu       REAL    NOT NULL DEFAULT 0,
    mem_pct   REAL    NOT NULL DEFAULT 0,
    rx_speed  REAL    NOT NULL DEFAULT 0,   -- bytes/s
    tx_speed  REAL    NOT NULL DEFAULT 0,
    rx_total  INTEGER NOT NULL DEFAULT 0,
    tx_total  INTEGER NOT NULL DEFAULT 0,
    conns     INTEGER NOT NULL DEFAULT 0,
    score     INTEGER NOT NULL DEFAULT 100
);
CREATE INDEX IF NOT EXISTS idx_metrics_ts ON metrics(ts);

CREATE TABLE IF NOT EXISTS traffic_hourly (
    hour      INTEGER NOT NULL,
    user_id   INTEGER NOT NULL,
    up        INTEGER NOT NULL DEFAULT 0,
    down      INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (hour, user_id)
);

CREATE TABLE IF NOT EXISTS events (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    ts       INTEGER NOT NULL,
    level    TEXT    NOT NULL DEFAULT 'info',
    kind     TEXT    NOT NULL DEFAULT 'system',
    message  TEXT    NOT NULL,
    meta     TEXT    NOT NULL DEFAULT '{}',
    seen     INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts DESC);

CREATE TABLE IF NOT EXISTS achievements (
    user_id  INTEGER NOT NULL,
    code     TEXT    NOT NULL,
    ts       INTEGER NOT NULL,
    PRIMARY KEY (user_id, code)
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Temporary per-user speed boost (idea #7)
CREATE TABLE IF NOT EXISTS boosts (
    user_id    INTEGER PRIMARY KEY,
    started_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL
);

-- Self-service trial links (idea #19)
CREATE TABLE IF NOT EXISTS trials (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    code        TEXT    NOT NULL UNIQUE,
    quota_gb    REAL    NOT NULL DEFAULT 1,
    hours       INTEGER NOT NULL DEFAULT 24,
    max_claims  INTEGER NOT NULL DEFAULT 10,
    claims      INTEGER NOT NULL DEFAULT 0,
    per_day     INTEGER NOT NULL DEFAULT 5,
    enabled     INTEGER NOT NULL DEFAULT 1,
    created_at  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS trial_claims (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    trial_id INTEGER NOT NULL,
    user_id  INTEGER NOT NULL,
    ip       TEXT    NOT NULL DEFAULT '',
    ts       INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_claims_ts ON trial_claims(ts DESC);

-- Exit-IP history per country location (idea: pin the most stable exit).
-- One row per (country, exit IP) with first/last sighting and how many
-- times it was observed, so the panel can rank exits by stability.
CREATE TABLE IF NOT EXISTS loc_exits (
    code       TEXT    NOT NULL,
    ip         TEXT    NOT NULL,
    first_seen INTEGER NOT NULL,
    last_seen  INTEGER NOT NULL,
    count      INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (code, ip)
);
CREATE INDEX IF NOT EXISTS idx_loc_exits_code ON loc_exits(code, last_seen DESC);
"""


def conn() -> sqlite3.Connection:
    """Per-thread connection."""
    c = getattr(_local, "conn", None)
    if c is None:
        os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
        c = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=NORMAL")
        c.execute("PRAGMA foreign_keys=ON")
        c.execute("PRAGMA busy_timeout=30000")
        _local.conn = c
    return c


# Columns added after the first release. CREATE TABLE IF NOT EXISTS does
# nothing to a table that already exists, so a new column has to be added
# explicitly or every existing deployment breaks on upgrade.
#
# Each entry is (table, column, full DDL). Applied only when missing, so
# running this repeatedly is harmless.
MIGRATIONS = [
    # Which transports appear in this user's subscription. Empty means
    # "everything", which is what every pre-existing row gets, so the
    # upgrade cannot change what an existing user already receives.
    ("users", "allowed_kinds", "TEXT NOT NULL DEFAULT ''"),
]


def _migrate(c) -> None:
    for table, column, ddl in MIGRATIONS:
        cols = {r[1] for r in c.execute(f"PRAGMA table_info({table})")}
        if column not in cols:
            c.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
    # Clean up legacy device_limit column if present (feature removed — dead code)
    try:
        cols = {r[1] for r in c.execute("PRAGMA table_info(users)")}
        if "device_limit" in cols:
            # SQLite < 3.35 lacks DROP COLUMN; recreate table without it
            try:
                c.execute("ALTER TABLE users DROP COLUMN device_limit")
            except Exception:
                pass  # legacy installs keep the column harmlessly
    except Exception:
        pass


def init() -> None:
    c = conn()
    with _write_lock:
        c.executescript(SCHEMA)
        _migrate(c)
        c.commit()
        # Country exits now start disabled by default: the panel is the
        # only place they get activated. Any previously-seeded set is
        # cleared exactly once (guarded by a flag so a later db.init()
        # — e.g. from the metrics loop or the nginx bootstrap — never
        # wipes a set the admin chose afterwards).
        flag_row = c.execute(
            "SELECT value FROM settings WHERE key=?",
            ("locations_reset_done",)).fetchone()

        def _is_truthy(v) -> bool:
            if v is None:
                return False
            try:
                parsed = json.loads(v["value"]) if hasattr(v, "__getitem__") else json.loads(v)
                return bool(parsed)
            except (ValueError, TypeError, KeyError, AttributeError):
                # handle non-JSON stored values like "true"/"1"
                try:
                    raw = v["value"] if hasattr(v, "__getitem__") else str(v)
                    return str(raw).strip().lower() in ("true", "1", "yes")
                except Exception:
                    return False

        if _is_truthy(flag_row):
            return
        # Need to decide: was this a legacy DB that needs clearing?
        row = c.execute("SELECT value FROM settings WHERE key=?",
                        ("locations_enabled",)).fetchone()
        if row is not None:
            try:
                cur = json.loads(row["value"])
            except (ValueError, TypeError):
                cur = row["value"]
            if cur:
                c.execute(
                    "INSERT INTO settings(key,value) VALUES(?,?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    ("locations_enabled", json.dumps([])))
        # Fresh databases get the empty list explicitly so the panel
        # always sees a real value, and the reset flag is set so a
        # later init() never wipes an admin's choice.
        c.execute(
            "INSERT INTO settings(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            ("locations_enabled", json.dumps([])))
        c.execute(
            "INSERT INTO settings(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            ("locations_reset_done", json.dumps(True)))
        c.commit()


def query(sql: str, args: tuple = ()) -> list[sqlite3.Row]:
    return conn().execute(sql, args).fetchall()


def one(sql: str, args: tuple = ()) -> sqlite3.Row | None:
    return conn().execute(sql, args).fetchone()


def execute(sql: str, args: tuple = ()) -> sqlite3.Cursor:
    c = conn()
    with _write_lock:
        cur = c.execute(sql, args)
        c.commit()
        return cur


def executemany(sql: str, seq) -> None:
    c = conn()
    with _write_lock:
        c.executemany(sql, seq)
        c.commit()


# ── settings helpers ─────────────────────────────────────────────────────────

_DEFAULT_SETTINGS: dict[str, Any] = {
    "turbo_mode": False,
    "decoy_enabled": True,
    "alert_cpu": 85,
    "alert_quota_pct": 90,
    # Smart fragment (anti-DPI): "" = off, else light/medium/aggressive.
    "smart_fragment": "",
}


def get_setting(key: str, default: Any = None) -> Any:
    row = one("SELECT value FROM settings WHERE key=?", (key,))
    if row is None:
        return _DEFAULT_SETTINGS.get(key, default)
    try:
        return json.loads(row["value"])
    except (ValueError, TypeError):
        return row["value"]


def set_setting(key: str, value: Any) -> None:
    execute(
        "INSERT INTO settings(key,value) VALUES(?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, json.dumps(value)),
    )


def all_settings() -> dict[str, Any]:
    out = dict(_DEFAULT_SETTINGS)
    for r in query("SELECT key,value FROM settings"):
        try:
            out[r["key"]] = json.loads(r["value"])
        except (ValueError, TypeError):
            out[r["key"]] = r["value"]
    return out


# ── events ───────────────────────────────────────────────────────────────────

def log_event(message: str, kind: str = "system", level: str = "info",
              meta: dict | None = None) -> None:
    execute(
        "INSERT INTO events(ts,level,kind,message,meta) VALUES(?,?,?,?,?)",
        (int(time.time()), level, kind, message, json.dumps(meta or {})),
    )


# ── users ────────────────────────────────────────────────────────────────────

def new_uuid() -> str:
    return str(_uuid.uuid4())


def new_token(n: int = 24) -> str:
    return secrets.token_urlsafe(n).replace("-", "").replace("_", "")[:32]


def create_user(username: str, quota_gb: float = 0, days: int = 0,
                note: str = "") -> dict:
    now = int(time.time())
    expires = now + int(days * 86400) if days and days > 0 else 0
    quota = int(quota_gb * 1024 ** 3) if quota_gb and quota_gb > 0 else 0
    last_exc = None
    for _ in range(5):
        try:
            cur = execute(
                """INSERT INTO users(username,uuid,trojan_pass,ss_pass,sub_token,
                                     quota_bytes,expires_at,note,
                                     created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (username, new_uuid(), new_token(16), new_token(16), new_token(20),
                 quota, expires, note, now, now),
            )
            log_event(f"User '{username}' created", kind="user", meta={"id": cur.lastrowid})
            return get_user(cur.lastrowid)  # type: ignore[arg-type]
        except sqlite3.IntegrityError as e:
            last_exc = e
            # username collision is a user error — do not retry
            if "users.username" in str(e):
                raise
            continue
    raise last_exc  # type: ignore[misc]


def get_user(uid: int) -> dict | None:
    r = one("SELECT * FROM users WHERE id=?", (uid,))
    return dict(r) if r else None


def get_user_by_token(token: str) -> dict | None:
    r = one("SELECT * FROM users WHERE sub_token=?", (token,))
    return dict(r) if r else None


def get_user_by_uuid(u: str) -> dict | None:
    r = one("SELECT * FROM users WHERE uuid=?", (u,))
    return dict(r) if r else None


def list_users() -> list[dict]:
    return [dict(r) for r in query("SELECT * FROM users ORDER BY id")]


def active_users() -> list[dict]:
    """Users that should currently be present in the Xray config."""
    now = int(time.time())
    rows = query(
        """SELECT * FROM users
           WHERE enabled=1
             AND (expires_at=0 OR expires_at > ?)
             AND (quota_bytes=0 OR used_up+used_down < quota_bytes)
           ORDER BY id""",
        (now,),
    )
    return [dict(r) for r in rows]


def update_user(uid: int, **fields) -> dict | None:
    allowed = {
        "username", "quota_bytes", "expires_at",
        "enabled", "note", "uuid", "trojan_pass", "ss_pass", "sub_token",
        "used_up", "used_down", "xp", "last_seen", "allowed_kinds",
    }
    sets, args = [], []
    for k, v in fields.items():
        if k in allowed:
            sets.append(f"{k}=?")
            args.append(v)
    if not sets:
        return get_user(uid)
    sets.append("updated_at=?")
    args.append(int(time.time()))
    args.append(uid)
    execute(f"UPDATE users SET {', '.join(sets)} WHERE id=?", tuple(args))
    return get_user(uid)


def delete_user(uid: int) -> None:
    u = get_user(uid)
    execute("DELETE FROM users WHERE id=?", (uid,))
    execute("DELETE FROM achievements WHERE user_id=?", (uid,))
    execute("DELETE FROM traffic_hourly WHERE user_id=?", (uid,))
    if u:
        log_event(f"User '{u['username']}' deleted", kind="user", level="warn")


# ── metrics retention ────────────────────────────────────────────────────────

def prune(days: int = 31) -> None:
    cutoff = int(time.time()) - days * 86400
    execute("DELETE FROM metrics WHERE ts < ?", (cutoff,))
    execute("DELETE FROM traffic_hourly WHERE hour < ?", (cutoff,))
    execute("DELETE FROM events WHERE ts < ?", (int(time.time()) - 7 * 86400,))


# ── boosts (idea #7) ─────────────────────────────────────────────────────────

def boost_start(uid: int, minutes: int = 30) -> dict:
    now = int(time.time())
    exp = now + minutes * 60
    execute(
        "INSERT INTO boosts(user_id,started_at,expires_at) VALUES(?,?,?) "
        "ON CONFLICT(user_id) DO UPDATE SET started_at=excluded.started_at, "
        "expires_at=excluded.expires_at",
        (uid, now, exp),
    )
    log_event(f"Boost activated for user #{uid} ({minutes}m)", kind="boost")
    return {"active": True, "started_at": now, "expires_at": exp,
            "remaining": exp - now}


def boost_stop(uid: int) -> None:
    execute("DELETE FROM boosts WHERE user_id=?", (uid,))


def boost_status(uid: int) -> dict:
    r = one("SELECT * FROM boosts WHERE user_id=?", (uid,))
    now = int(time.time())
    if not r or r["expires_at"] <= now:
        if r:
            execute("DELETE FROM boosts WHERE user_id=?", (uid,))
        return {"active": False, "remaining": 0}
    return {"active": True, "started_at": r["started_at"],
            "expires_at": r["expires_at"], "remaining": r["expires_at"] - now}


def boosts_active() -> list[int]:
    now = int(time.time())
    execute("DELETE FROM boosts WHERE expires_at <= ?", (now,))
    return [r["user_id"] for r in query("SELECT user_id FROM boosts")]


# ── trials (idea #19) ────────────────────────────────────────────────────────

def trial_create(quota_gb: float = 1, hours: int = 24, max_claims: int = 10,
                 per_day: int = 5) -> dict:
    last_exc = None
    for _ in range(5):
        try:
            code = new_token(12)
            cur = execute(
                "INSERT INTO trials(code,quota_gb,hours,max_claims,per_day,created_at) "
                "VALUES(?,?,?,?,?,?)",
                (code, quota_gb, hours, max_claims, per_day, int(time.time())),
            )
            log_event(f"Trial link created ({quota_gb}GB / {hours}h)", kind="trial")
            return trial_get_by_id(cur.lastrowid)  # type: ignore[arg-type]
        except sqlite3.IntegrityError as e:
            last_exc = e
            continue
    raise last_exc  # type: ignore[misc]


def trial_get_by_id(tid: int) -> dict | None:
    r = one("SELECT * FROM trials WHERE id=?", (tid,))
    return dict(r) if r else None


def trial_get(code: str) -> dict | None:
    r = one("SELECT * FROM trials WHERE code=?", (code,))
    return dict(r) if r else None


def trial_list() -> list[dict]:
    out = []
    for r in query("SELECT * FROM trials ORDER BY id DESC"):
        d = dict(r)
        d["claimed_today"] = trial_claims_today(d["id"])
        out.append(d)
    return out


def trial_claims_today(tid: int) -> int:
    since = int(time.time()) - 86400
    r = one("SELECT COUNT(*) c FROM trial_claims WHERE trial_id=? AND ts>=?",
            (tid, since))
    return int(r["c"]) if r else 0


def trial_claimed_by_ip(tid: int, ip: str, window: int = 86400) -> bool:
    if not ip:
        return False
    r = one(
        "SELECT 1 FROM trial_claims WHERE trial_id=? AND ip=? AND ts>=?",
        (tid, ip, int(time.time()) - window),
    )
    return r is not None


def trial_record(tid: int, uid: int, ip: str) -> None:
    execute("INSERT INTO trial_claims(trial_id,user_id,ip,ts) VALUES(?,?,?,?)",
            (tid, uid, ip, int(time.time())))
    execute("UPDATE trials SET claims=claims+1 WHERE id=?", (tid,))


def trial_delete(tid: int) -> None:
    execute("DELETE FROM trials WHERE id=?", (tid,))
    execute("DELETE FROM trial_claims WHERE trial_id=?", (tid,))


def trial_toggle(tid: int, enabled: bool) -> None:
    execute("UPDATE trials SET enabled=? WHERE id=?", (1 if enabled else 0, tid))


# ── per-user analytics (idea #4) ─────────────────────────────────────────────

def user_history(uid: int, window: str = "24h") -> list[dict]:
    """Bucketed traffic for one user, from the hourly rollup table."""
    spans = {"24h": 86400, "7d": 604800, "30d": 2592000}
    span = spans.get(window, 86400)
    now = int(time.time())
    since = now - span
    step = 3600 if span <= 604800 else 86400
    rows = query(
        f"""SELECT (hour/{step})*{step} AS b,
                   SUM(up) u, SUM(down) d
            FROM traffic_hourly
            WHERE user_id=? AND hour>=?
            GROUP BY b ORDER BY b""",
        (uid, since),
    )
    return [{"t": r["b"], "up": int(r["u"] or 0), "down": int(r["d"] or 0),
             "total": int((r["u"] or 0) + (r["d"] or 0))} for r in rows]


def user_weekly(uid: int) -> dict:
    """Numbers behind the weekly report (idea #14)."""
    now = int(time.time())
    this_start = now - 604800
    prev_start = now - 1209600

    def total(a, b):
        r = one("SELECT SUM(up) u, SUM(down) d FROM traffic_hourly "
                "WHERE user_id=? AND hour>=? AND hour<?", (uid, a, b))
        return int(r["u"] or 0), int(r["d"] or 0)

    up, down = total(this_start, now)
    pup, pdown = total(prev_start, this_start)
    cur_total, prev_total = up + down, pup + pdown

    rows = query(
        "SELECT hour, SUM(up+down) v FROM traffic_hourly "
        "WHERE user_id=? AND hour>=? GROUP BY hour ORDER BY v DESC LIMIT 1",
        (uid, this_start))
    peak = None
    if rows:
        lt = time.localtime(rows[0]["hour"])
        peak = {"ts": rows[0]["hour"], "hour": lt.tm_hour,
                "bytes": int(rows[0]["v"] or 0)}

    by_hour = query(
        "SELECT hour, SUM(up+down) v FROM traffic_hourly "
        "WHERE user_id=? AND hour>=? GROUP BY hour ORDER BY hour",
        (uid, this_start))
    days: dict[int, int] = {}
    hours: dict[int, int] = {}
    for r in by_hour:
        lt = time.localtime(r["hour"])
        days[lt.tm_wday] = days.get(lt.tm_wday, 0) + int(r["v"] or 0)
        hours[lt.tm_hour] = hours.get(lt.tm_hour, 0) + int(r["v"] or 0)

    active_days = len(days)
    busiest_day = max(days, key=days.get) if days else None
    busiest_hour = max(hours, key=hours.get) if hours else None

    change = None
    if prev_total > 0:
        change = round((cur_total - prev_total) / prev_total * 100, 1)
    elif cur_total > 0:
        change = 100.0

    return {
        "up": up, "down": down, "total": cur_total,
        "prev_total": prev_total, "change_pct": change,
        "peak": peak, "active_days": active_days,
        "busiest_day": busiest_day, "busiest_hour": busiest_hour,
        "daily": [{"dow": k, "bytes": v} for k, v in sorted(days.items())],
        "hourly": [{"hour": k, "bytes": v} for k, v in sorted(hours.items())],
        "avg_per_day": int(cur_total / 7),
        "from": this_start, "to": now,
    }
