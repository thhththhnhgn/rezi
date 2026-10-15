"""
ULTRA GAMING VPN — system + per-user metrics collector.

Runs in a background thread:
  * every SAMPLE_INTERVAL s  -> read /proc, compute deltas, cache live snapshot
  * every PERSIST_INTERVAL s -> append a row to `metrics` (time-series)
  * every SYNC_INTERVAL s    -> pull & reset xray per-user counters into DB,
                                enforce quota/expiry, grant achievements
"""

from __future__ import annotations

import os
import threading
import time

from . import db, gamify, xray

# Gaming-optimized intervals:
# SAMPLE: 1s = faster dashboard updates and quicker reactions to spikes
# SYNC:   5s = faster quota enforcement + achievement grants
# PERSIST: 30s = denser history charts (half the previous interval)
SAMPLE_INTERVAL = 1
PERSIST_INTERVAL = 30
SYNC_INTERVAL = 5
PRUNE_INTERVAL = 3600

XRAY_PORTS = {7001, 7002, 7003, 7004, 7005}
_HEX_PORTS = {format(p, "04X") for p in XRAY_PORTS}

_state = {
    "cpu_idle": None, "cpu_total": None,
    "rx": None, "tx": None, "t": None,
    "peak_rx": 0.0, "peak_tx": 0.0,
    "boot": time.time(),
}
_snapshot: dict = {}
_history: list[dict] = []          # rolling in-memory window for the live graph
_lock = threading.Lock()
_stop = threading.Event()
_subscribers: set = set()
_sub_lock = threading.Lock()


# ── /proc readers ────────────────────────────────────────────────────────────

def _cpu() -> tuple[int, int]:
    try:
        with open("/proc/stat") as f:
            p = f.readline().split()
        v = [int(x) for x in p[1:]]
        return v[3] + (v[4] if len(v) > 4 else 0), sum(v)
    except Exception:
        return 0, 1


def _mem() -> dict:
    m = {}
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                k, _, v = line.partition(":")
                m[k.strip()] = int(v.strip().split()[0])
    except Exception:
        pass
    total = m.get("MemTotal", 0)
    avail = m.get("MemAvailable", m.get("MemFree", 0))
    used = max(total - avail, 0)
    return {
        "total_mb": round(total / 1024, 1),
        "used_mb": round(used / 1024, 1),
        "free_mb": round(avail / 1024, 1),
        "percent": round(used / max(total, 1) * 100, 1),
    }


def _net() -> tuple[int, int]:
    rx = tx = 0
    try:
        with open("/proc/net/dev") as f:
            for line in f.readlines()[2:]:
                p = line.split()
                if not p or p[0].rstrip(":") == "lo":
                    continue
                rx += int(p[1])
                tx += int(p[9])
    except Exception:
        pass
    return rx, tx


def _loadavg() -> list[float]:
    try:
        with open("/proc/loadavg") as f:
            return [float(x) for x in f.read().split()[:3]]
    except Exception:
        return [0.0, 0.0, 0.0]


def _connections() -> dict:
    """ESTABLISHED sockets on xray inbound ports, split per port."""
    per_port = {p: 0 for p in XRAY_PORTS}
    total = 0
    for fname in ("/proc/net/tcp", "/proc/net/tcp6"):
        if not os.path.exists(fname):
            continue
        try:
            with open(fname) as f:
                for line in f.readlines()[1:]:
                    parts = line.split()
                    if len(parts) < 4 or parts[3] != "01":
                        continue
                    hexport = parts[1].split(":")[-1].upper()
                    if hexport in _HEX_PORTS:
                        per_port[int(hexport, 16)] += 1
                        total += 1
        except Exception:
            pass
    return {"total": total, "per_port": per_port}


def _uptime() -> tuple[str, int]:
    secs = int(time.time() - _state["boot"])
    try:
        with open("/proc/uptime") as f:
            secs = int(float(f.read().split()[0]))
    except Exception:
        pass
    d, rem = divmod(secs, 86400)
    h, rem = divmod(rem, 3600)
    m, s = divmod(rem, 60)
    txt = f"{d}d {h:02d}h {m:02d}m" if d else f"{h}h {m:02d}m {s:02d}s"
    return txt, secs


# ── server score ─────────────────────────────────────────────────────────────

def _score(cpu: float, mem_pct: float, load1: float, conns: int,
           xray_up: bool) -> int:
    """0-100 gaming health score. Penalise the things that hurt latency."""
    score = 100.0
    score -= max(0.0, cpu - 40) * 0.55          # cpu above 40% starts to bite
    score -= max(0.0, mem_pct - 70) * 0.45
    score -= max(0.0, load1 - 1.0) * 8.0
    score -= max(0, conns - 80) * 0.12
    if not xray_up:
        score -= 60
    return int(max(0, min(100, round(score))))


# ── sampling ─────────────────────────────────────────────────────────────────

def sample() -> dict:
    with _lock:
        now = time.time()

        idle, total = _cpu()
        if _state["cpu_idle"] is not None:
            di = idle - _state["cpu_idle"]
            dt = total - _state["cpu_total"]
            cpu = round(max(0.0, (1 - di / dt if dt > 0 else 0)) * 100, 1)
        else:
            cpu = 0.0
        _state["cpu_idle"], _state["cpu_total"] = idle, total

        mem = _mem()
        rx, tx = _net()
        if _state["rx"] is not None and _state["t"] is not None:
            el = max(now - _state["t"], 0.001)
            rx_spd = max(0.0, (rx - _state["rx"]) / el)
            tx_spd = max(0.0, (tx - _state["tx"]) / el)
        else:
            rx_spd = tx_spd = 0.0
        _state["rx"], _state["tx"], _state["t"] = rx, tx, now
        _state["peak_rx"] = max(_state["peak_rx"], rx_spd)
        _state["peak_tx"] = max(_state["peak_tx"], tx_spd)

        conns = _connections()
        load = _loadavg()
        up_txt, up_secs = _uptime()
        xray_up = xray.is_alive()
        score = _score(cpu, mem["percent"], load[0], conns["total"], xray_up)

        snap = {
            "cpu": cpu,
            "load": load,
            "memory": mem,
            "network": {
                "rx_total": rx, "tx_total": tx,
                "rx_speed": round(rx_spd, 1), "tx_speed": round(tx_spd, 1),
                "rx_total_mb": round(rx / 1048576, 2),
                "tx_total_mb": round(tx / 1048576, 2),
                "peak_rx": round(_state["peak_rx"], 1),
                "peak_tx": round(_state["peak_tx"], 1),
            },
            "connections": conns["total"],
            "per_port": conns["per_port"],
            "uptime": up_txt,
            "uptime_secs": up_secs,
            "xray": xray_up,
            "score": score,
            "timestamp": int(now),
        }

        global _snapshot
        _snapshot = snap
        _history.append({"t": int(now), "rx": rx_spd, "tx": tx_spd,
                         "cpu": cpu, "score": score})
        if len(_history) > 600:
            del _history[:-600]
        return snap


def latest() -> dict:
    return dict(_snapshot) if _snapshot else sample()


def live_history() -> list[dict]:
    return list(_history)


# ── per-user traffic sync ────────────────────────────────────────────────────

def sync_users() -> None:
    """Pull per-user counters out of xray, fold them into the DB."""
    deltas = xray.user_traffic_delta()
    if not deltas:
        return

    users = {f"{u['id']}.{u['username']}": u for u in db.list_users()}
    now = int(time.time())
    hour = now - (now % 3600)
    changed = False

    for email, (up, down) in deltas.items():
        u = users.get(email)
        if not u or (up == 0 and down == 0):
            continue
        db.execute(
            "UPDATE users SET used_up=used_up+?, used_down=used_down+?, "
            "last_seen=?, updated_at=? WHERE id=?",
            (up, down, now, now, u["id"]),
        )
        db.execute(
            "INSERT INTO traffic_hourly(hour,user_id,up,down) VALUES(?,?,?,?) "
            "ON CONFLICT(hour,user_id) DO UPDATE SET "
            "up=up+excluded.up, down=down+excluded.down",
            (hour, u["id"], up, down),
        )
        changed = True

    if not changed:
        return

    # post-update: xp, achievements, quota enforcement
    peak = max(_state["peak_rx"], _state["peak_tx"])
    quota_alert = float(db.get_setting("alert_quota_pct", 90))
    disable_ids = []

    for u in db.list_users():
        fresh = db.get_user(u["id"])
        if not fresh:
            continue
        new_xp = gamify.xp_for(fresh)
        if new_xp != fresh["xp"]:
            db.execute("UPDATE users SET xp=? WHERE id=?", (new_xp, fresh["id"]))
            fresh["xp"] = new_xp
        gamify.evaluate(fresh, peak)

        used = fresh["used_up"] + fresh["used_down"]
        if fresh["quota_bytes"] > 0:
            pct = used / fresh["quota_bytes"] * 100
            if pct >= 100 and fresh["enabled"]:
                disable_ids.append(fresh["id"])
                db.log_event(f"Quota exhausted for '{fresh['username']}'",
                             kind="quota", level="warn",
                             meta={"user_id": fresh["id"]})
            elif pct >= quota_alert:
                db.log_event(
                    f"'{fresh['username']}' reached {pct:.0f}% of quota",
                    kind="quota", level="warn", meta={"user_id": fresh["id"]})
        if fresh["expires_at"] and fresh["expires_at"] < now and fresh["enabled"]:
            disable_ids.append(fresh["id"])
            db.log_event(f"Subscription expired for '{fresh['username']}'",
                         kind="quota", level="warn",
                         meta={"user_id": fresh["id"]})

    if disable_ids:
        for uid in set(disable_ids):
            db.execute("UPDATE users SET enabled=0 WHERE id=?", (uid,))
        xray.reload()


def persist(snap: dict) -> None:
    db.execute(
        "INSERT OR REPLACE INTO metrics"
        "(ts,cpu,mem_pct,rx_speed,tx_speed,rx_total,tx_total,conns,score) "
        "VALUES(?,?,?,?,?,?,?,?,?)",
        (snap["timestamp"], snap["cpu"], snap["memory"]["percent"],
         snap["network"]["rx_speed"], snap["network"]["tx_speed"],
         snap["network"]["rx_total"], snap["network"]["tx_total"],
         snap["connections"], snap["score"]),
    )


def history(window: str = "24h") -> list[dict]:
    now = int(time.time())
    spans = {"1h": 3600, "6h": 21600, "24h": 86400,
             "7d": 604800, "30d": 2592000}
    span = spans.get(window, 86400)
    buckets = 120
    step = max(span // buckets, 60)
    since = now - span

    rows = db.query(
        f"""SELECT (ts/{step})*{step} AS b,
                   AVG(cpu) c, AVG(mem_pct) m,
                   AVG(rx_speed) rx, AVG(tx_speed) tx,
                   MAX(conns) k, AVG(score) s
            FROM metrics WHERE ts >= ?
            GROUP BY b ORDER BY b""",
        (since,),
    )
    return [{"t": r["b"], "cpu": round(r["c"] or 0, 1),
             "mem": round(r["m"] or 0, 1), "rx": round(r["rx"] or 0, 1),
             "tx": round(r["tx"] or 0, 1), "conns": int(r["k"] or 0),
             "score": int(r["s"] or 0)} for r in rows]


def heatmap(days: int = 7) -> list[dict]:
    """Hourly traffic totals for a weekday x hour heatmap."""
    since = int(time.time()) - days * 86400
    rows = db.query(
        "SELECT hour, SUM(up+down) v FROM traffic_hourly "
        "WHERE hour >= ? GROUP BY hour ORDER BY hour", (since,))
    out = []
    for r in rows:
        lt = time.localtime(r["hour"])
        out.append({"t": r["hour"], "dow": lt.tm_wday, "hour": lt.tm_hour,
                    "bytes": int(r["v"] or 0)})
    return out


def top_users(limit: int = 10) -> list[dict]:
    rows = db.query(
        "SELECT id,username,used_up,used_down,xp,last_seen,enabled "
        "FROM users ORDER BY (used_up+used_down) DESC LIMIT ?", (limit,))
    out = []
    for r in rows:
        d = dict(r)
        d["total"] = d["used_up"] + d["used_down"]
        d["rank"] = gamify.rank_for(d["xp"])
        out.append(d)
    return out


# ── SSE fan-out ──────────────────────────────────────────────────────────────

def subscribe() -> "queue.Queue":
    import queue
    q = queue.Queue(maxsize=20)
    with _sub_lock:
        _subscribers.add(q)
    return q


def unsubscribe(q) -> None:
    with _sub_lock:
        _subscribers.discard(q)


def _broadcast(snap: dict) -> None:
    import queue as _q
    with _sub_lock:
        dead = []
        for q in _subscribers:
            try:
                q.put_nowait(snap)
            except _q.Full:
                dead.append(q)
        for q in dead:
            _subscribers.discard(q)


# ── background loop ──────────────────────────────────────────────────────────

def _loop() -> None:
    last_persist = last_sync = last_prune = last_watch = 0.0
    alert_cpu_since = 0.0
    while not _stop.is_set():
        try:
            snap = sample()
            _broadcast(snap)
            now = time.time()

            if now - last_persist >= PERSIST_INTERVAL:
                persist(snap)
                last_persist = now

            if now - last_sync >= SYNC_INTERVAL:
                sync_users()
                last_sync = now

            if now - last_prune >= PRUNE_INTERVAL:
                db.prune()
                last_prune = now

            # Watchdog: if Xray died, bring it back (throttled inside).
            # Checked more often than the other jobs so a dead tunnel is
            # restored in seconds, not minutes.
            if now - last_watch >= 10:
                xray.ensure_alive()
                last_watch = now

            # sustained-high-CPU alert (needs 30s above threshold)
            thr = float(db.get_setting("alert_cpu", 85))
            if snap["cpu"] >= thr:
                if alert_cpu_since == 0:
                    alert_cpu_since = now
                elif now - alert_cpu_since >= 30:
                    db.log_event(f"CPU sustained at {snap['cpu']}%",
                                 kind="alert", level="warn")
                    alert_cpu_since = now + 240   # cool-down
            else:
                alert_cpu_since = 0.0
        except Exception as e:  # never let the collector die
            try:
                db.log_event(f"metrics loop error: {e}", kind="system",
                             level="error")
            except Exception:
                pass
        _stop.wait(SAMPLE_INTERVAL)


_thread: threading.Thread | None = None


def start() -> None:
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="metrics", daemon=True)
    _thread.start()


def shutdown() -> None:
    _stop.set()
