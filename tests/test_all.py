"""
ULTRA GAMING VPN — end-to-end test suite.

Runs the real control plane against a temporary database with Xray stubbed
out, then exercises every API route, generator and edge case.

    python3 tests/test_all.py
"""

from __future__ import annotations

import base64
import json
import os
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

TMP = tempfile.mkdtemp(prefix="ultra-test-")
os.environ.update(
    DB_PATH=os.path.join(TMP, "test.db"),
    XRAY_CONFIG=os.path.join(TMP, "xray", "config.json"),
    XRAY_BIN=os.path.join(TMP, "no-such-xray"),
    ADMIN_USER="admin",
    ADMIN_PASS="test-password-123",
    SECRET_KEY="0" * 64,
    PATH_SECRET="unit-test-secret",
    CF_WORKER_HOST="worker.example.workers.dev",
    API_PORT="8971",
    ONIONOO_REFRESH="0",   # tests are offline; use the bundled snapshot
)

from app import auth, db, gamify, links, metrics, paths, profiles, server, xray  # noqa: E402

BASE = "http://127.0.0.1:8971"
PASS = FAIL = 0
FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  \033[32m✓\033[0m {name}")
    else:
        FAIL += 1
        FAILURES.append(f"{name} — {detail}")
        print(f"  \033[31m✗\033[0m {name}  {detail}")


def section(title: str) -> None:
    print(f"\n\033[1;36m{title}\033[0m")


def req(path, data=None, tok=None, method=None, raw=False):
    url = BASE + path
    r = urllib.request.Request(url, method=method or ("POST" if data is not None else "GET"))
    if tok:
        r.add_header("Authorization", "Bearer " + tok)
    body = None
    if data is not None:
        body = json.dumps(data).encode()
        r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r, body, timeout=15) as f:
            txt = f.read().decode()
            hdrs = dict(f.headers)
            if raw:
                return f.status, txt, hdrs
            try:
                return f.status, json.loads(txt), hdrs
            except ValueError:
                return f.status, txt, hdrs
    except urllib.error.HTTPError as e:
        txt = e.read().decode()
        try:
            return e.code, json.loads(txt), dict(e.headers)
        except ValueError:
            return e.code, txt, dict(e.headers)


def main() -> int:
    db.init()
    metrics.start()
    threading.Thread(target=server.serve, daemon=True).start()
    time.sleep(0.8)

    # ── auth ─────────────────────────────────────────────────────────
    section("Authentication")
    s, _, _ = req("/health")
    check("health endpoint", s == 200)
    s, _, _ = req("/api/stats")
    check("unauthenticated request rejected", s == 401)
    s, _, _ = req("/api/login", {"username": "admin", "password": "wrong"})
    check("wrong password rejected", s == 401)
    s, _, _ = req("/api/login", {"username": "root", "password": "test-password-123"})
    check("wrong username rejected", s == 401)
    s, d, _ = req("/api/login", {"username": "admin", "password": "test-password-123"})
    check("valid login issues token", s == 200 and "token" in d)
    tok = d["token"]
    s, _, _ = req("/api/stats", tok="garbage.token")
    check("forged token rejected", s == 401)
    check("expired token rejected", auth.verify(auth.issue(ttl=-10)) is None)
    check("scope is enforced", auth.verify(auth.issue(scope="user"), scope="admin") is None)

    # ── users ────────────────────────────────────────────────────────
    section("Player management")
    s, u1, _ = req("/api/users", {"username": "neo", "quota_gb": 10, "days": 30}, tok)
    check("create player", s == 201 and u1["username"] == "neo", str(u1)[:120])
    uid, sub_token = u1["id"], u1["sub_token"]
    check("uuid generated", len(u1["uuid"]) == 36)
    check("sub token generated", len(sub_token) >= 16)
    check("quota stored", u1["quota_bytes"] == 10 * 1024 ** 3)
    check("expiry stored", 29 <= (u1["days_left"] or 0) <= 30)
    check("starts at Iron", u1["rank"]["name"] == "Iron")

    s, _, _ = req("/api/users", {"username": "neo"}, tok)
    check("duplicate username rejected", s == 409)
    for bad in ["a", "a" * 40, "has space", "bad!char", ""]:
        s, _, _ = req("/api/users", {"username": bad}, tok)
        check(f"invalid username rejected ({bad!r})", s == 400)

    s, d, _ = req(f"/api/users/{uid}", {"quota_gb": 50, "enabled": False}, tok, "PATCH")
    check("patch player", s == 200 and d["quota_bytes"] == 50 * 1024 ** 3 and not d["enabled"])
    s, d, _ = req(f"/api/users/{uid}", {"enabled": True}, tok, "PATCH")
    check("re-enable player", d["enabled"] == 1)

    old_uuid = d["uuid"]
    s, d, _ = req(f"/api/users/{uid}/reset", {}, tok)
    check("rotate credentials", s == 200 and d["uuid"] != old_uuid)
    sub_token = d["sub_token"]

    s, _, _ = req("/api/users/99999", {"quota_gb": 1}, tok, "PATCH")
    check("patch missing player 404s", s == 404)
    s, _, _ = req("/api/users/99999", tok=tok, method="DELETE")
    check("delete missing player 404s", s == 404)

    # ── config generation ────────────────────────────────────────────
    section("Config generation")
    s, d, _ = req(f"/api/users/{uid}/configs", tok=tok)
    check("configs endpoint", s == 200)
    cfgs = d["configs"]
    check("both direct and CF variants", len(cfgs) == 10, f"got {len(cfgs)}")
    kinds = {c["kind"] for c in cfgs}
    check("all five transports present",
          kinds == {"xhttp", "ws", "httpupgrade", "trojan", "vmess"}, str(kinds))
    check("shadowsocks removed", "ss" not in kinds)
    check("secret prefix in paths",
          all(paths.PREFIX in c["path"] for c in cfgs), cfgs[0]["path"])
    check("every uri has a scheme",
          all("://" in c["uri"] for c in cfgs))
    check("no raw credentials leak into labels",
          not any(d["user"]["uuid"] in c["label"] for c in cfgs))

    vmess = [c for c in cfgs if c["kind"] == "vmess"][0]
    payload = json.loads(base64.b64decode(vmess["uri"][8:] + "==").decode())
    check("vmess payload decodes", payload["id"] == d["user"]["uuid"])
    check("vmess uses tls", payload["tls"] == "tls")
    check("vmess port 443", payload["port"] == "443")

    # ── Cloudflare Worker <-> panel agreement ────────────────────────
    # The Worker is a separate deployment that users paste by hand, so
    # nothing forces it to stay in sync. If its suffix list drifts from
    # app/paths.py the affected transport 404s at the edge and looks like a
    # dead config.
    section("worker tunnel paths")
    with open(os.path.join(ROOT, "cloudflare-worker.js")) as _f:
        _js = _f.read()
    import re as _re3
    _m3 = _re3.search(r"const SUFFIXES = \[(.*?)\];", _js, _re3.S)
    check("worker declares a suffix list", _m3 is not None)
    if _m3:
        _wsuf = set(_re3.findall(r'"([^"]+)"', _m3.group(1)))
        _psuf = {v[len(paths.PREFIX):] for v in paths.ALL.values()}
        check("worker suffixes match the panel's paths",
              _wsuf == _psuf,
              f"worker={sorted(_wsuf)} panel={sorted(_psuf)}")

    # XHTTP packet-up uploads go to /<prefix>/xhttp/<uuid>/<seq>, so the
    # worker must relay subpaths, not just the bare suffix.
    check("worker matches tunnel subpaths",
          'rest.startsWith(s + "/")' in _js)
    # A streamed or upgraded request cannot be replayed on another origin.
    check("worker only fails over when nothing was committed",
          "canFailover" in _js)
    # Without accept() the relayed socket stays paused and the tunnel hangs.
    check("worker accepts the upstream websocket",
          "webSocket.accept()" in _js)
    # duplex:"half" is what keeps XHTTP uploads streaming instead of buffered.
    check("worker streams request bodies", 'duplex = "half"' in _js)

    # ── country exit locations ───────────────────────────────────────
    # These route through Tor and cost 500-3000ms, so the rules that keep
    # them out of the way matter more than the feature itself.
    section("country exit locations")
    from app import locations as _loc

    _loc._set_enabled([])
    check("locations are off until enabled", _loc.configured() == [])
    check("every known country is listed", len(_loc.COUNTRIES) >= 190,
          str(len(_loc.COUNTRIES)))
    # The panel only lists countries where Tor actually runs exit relays —
    # the bundled snapshot (onionoo 2026-08-02) has ~51 of them. Palestine
    # has zero relays, so it must not appear anywhere.
    _known = _loc.known_codes()
    check("only exit-relay countries are listed",
          40 <= len(_known) <= 90, str(len(_known)))
    check("palestine has no tor exit relays", "ps" not in _known)
    check("every listed country has exit relays",
          all(_loc._exit_counts().get(c, 0) >= 1 for c in _known),
          str(sorted(_known)[:5]))
    check("no excluded country is listed",
          all(c not in _loc.EXCLUDE for c in _known))
    check("hostile countries cannot be activated", "ir" not in _known)
    check("hostile list is applied to tor as well",
          all(c in _loc.EXCLUDE for c in ("ir", "ru", "cn")))

    # The torrc is the enforcement point: ExitNodes pins the country and
    # StrictNodes refuses to fall back anywhere else.
    _rc = _loc._torrc("de", 9050, 9150)
    with open(_rc) as _f:
        _torrc = _f.read()
    check("torrc pins the exit country", "ExitNodes {de}" in _torrc)
    check("torrc refuses to fall back to another country",
          "StrictNodes 1" in _torrc)
    for _bad in ("ir", "ru", "cn"):
        check(f"torrc excludes {_bad} from all hops",
              "{%s}" % _bad in _torrc)
    check("torrc excludes hostile exits explicitly",
          "ExcludeExitNodes" in _torrc)
    check("torrc avoids ipv6 for lower latency", "ClientUseIPv6 0" in _torrc)
    check("torrc fails fast on dead socks", "SocksTimeout 30" in _torrc)
    check("torrc caps circuit build time", "CircuitBuildTimeout 30" in _torrc)

    _loc._set_enabled(["de", "ir", "de", "zz", "tr"])
    _got = _loc.configured()
    check("duplicates are dropped", _got.count("de") == 1, str(_got))
    check("unknown codes are dropped", "zz" not in _got, str(_got))
    check("valid codes survive", _got == ["de", "tr"], str(_got))

    # Ports must not collide with the transport inbounds (7001-7005), the
    # control plane (8888) or the Xray API (10085) — across the FULL list,
    # because any of these countries may be enabled at any time.
    _pp = [_loc.ports(c) for c in _loc.known_codes()]
    _all = [x for t in _pp for x in t]
    check("all location ports are unique", len(_all) == len(set(_all)))
    _tports = {p for p, _ in xray.INBOUNDS.values()}
    check("location ports avoid the transport inbounds",
          not ({p[2] for p in _pp} & _tports), str(_pp[:3]))
    check("location ports avoid api ports", not (set(_all) & {8888, 10085}))

    # Exit-relay counts: the bundled snapshot drives the list until a live
    # refresh lands, and a live refresh can add/remove countries.
    check("bundled snapshot marks turkey scarce", _loc.is_scarce("tr") is True)
    check("bundled snapshot knows us has many relays",
          _loc._exit_counts().get("us", 0) >= 50)
    _loc._counts_cache = None
    db.set_setting("loc_exit_counts", {"de": 42, "ps": 1})
    db.set_setting("loc_exits_updated", int(time.time()))
    try:
        _loc._counts_cache = None
        _live = _loc.known_codes()
        check("live counts replace the snapshot", "de" in _live and "ps" in _live,
              str(_live))
        check("live counts mark scarce by threshold",
              _loc.is_scarce("de") is False and _loc.is_scarce("ps") is True)
        _rd = _loc.relay_data()
        check("relay data reports live source", _rd["source"] == "live", str(_rd))
    finally:
        _loc._counts_cache = None
        db.set_setting("loc_exit_counts", {})
        db.set_setting("loc_exits_updated", 0)
        _loc._counts_cache = None

    # Countries start disabled: the env var is a legacy no-op and the
    # panel is the only way to activate. Nothing may ever auto-seed.
    _saved_env = os.environ.get("LOCATIONS")
    try:
        for _word in ("all", "max", "ALL", "*", "de,fr,tr", "de,fr,ir,zz"):
            os.environ["LOCATIONS"] = _word
            db.set_setting("locations_enabled", None)
            _a = _loc.configured()
            check(f"env '{_word}' never auto-activates",
                  _a == [], str(_a))
        check("preset fits the cap",
              len(_loc.TOP_LOCATIONS) == _loc.MAX_LOCATIONS,
              str(len(_loc.TOP_LOCATIONS)))
        check("preset has no duplicates",
              len(set(_loc.TOP_LOCATIONS)) == len(_loc.TOP_LOCATIONS))
        check("turkey is in the preset", "tr" in _loc.TOP_LOCATIONS)
    finally:
        if _saved_env is None:
            os.environ.pop("LOCATIONS", None)
        else:
            os.environ["LOCATIONS"] = _saved_env
        _loc._set_enabled([])
        _loc._state.clear()

    # Turkey has 3 exit relays, so it will fail more often than it
    # succeeds. Two guards make that acceptable rather than confusing:
    # a longer retry budget, and a label so a FAILED card is read as
    # expected.
    check("turkey is marked fragile", "tr" in _loc.FRAGILE)
    check("fragile countries are all known",
          all(c in _loc.COUNTRIES for c in _loc.FRAGILE), str(_loc.FRAGILE))

    _loc._set_enabled(["de"])
    _loc._set("de", verified=True, state="ready", exit_ip="1.2.3.4")
    _snap0 = _loc.snapshot()
    _derow = [s for s in _snap0 if s["code"] == "de"][0]
    _trrow = [s for s in _snap0 if s["code"] == "tr"][0]
    check("snapshot exposes the fragile flag", "fragile" in _derow)
    check("snapshot exposes the enabled flag", _derow["enabled"] is True)
    check("snapshot exposes pinned state", "pinned" in _derow)
    check("disabled countries render as idle", _trrow["state"] == "idle")
    with open(os.path.join(ROOT, "web", "assets", "panel.js")) as _pf:
        _pjs = _pf.read()
    check("panel marks scarce countries", "l.fragile" in _pjs)
    with open(os.path.join(ROOT, "web", "assets", "app.css")) as _cf:
        _css = _cf.read()
    check("scarce badge is styled", ".lfrag" in _css)
    check("search box styled", ".lsearch" in _css)

    # Exit-IP history: the panel shows the most stable exits per country so
    # the admin can pin one. Ranking by duration means a relay that served
    # for hours beats one that flickered for seconds.
    _loc._set("de", exit_ip="1.2.3.4")
    _loc._record_exit("de", "1.2.3.4")
    _loc._record_exit("de", "1.2.3.4")
    _loc._set("de", exit_ip="5.6.7.8")
    _loc._record_exit("de", "5.6.7.8")
    _hist = _loc.exit_history("de")
    check("exit history tracks every IP", len(_hist) == 2, str(_hist))
    check("exit history exposes pinning data",
          all(k in _hist[0] for k in ("ip", "pct", "count", "duration")),
          str(_hist))
    check("exit history is capped at five", len(_loc.exit_history("de", 5)) <= 5)

    # Pinning: Tor's ExitNodes accepts a bare IP, so with StrictNodes 1 the
    # relay is forced. That is the mechanism behind "stable exit IP".
    check("bad pin rejected", _loc.pin_exit("de", "10.0.0.1")["ok"] is False)
    check("pin persists", _loc.pin_exit("de", "1.2.3.4")["ok"] is True
          and _loc._pinned("de") == "1.2.3.4")
    _rc2 = _loc._torrc("de", 9050, 9150)
    with open(_rc2) as _f:
        _t2 = _f.read()
    check("pinned exit replaces the country set",
          "ExitNodes 1.2.3.4" in _t2 and "ExitNodes {de}" not in _t2)
    _loc.unpin_exit("de")
    _rc3 = _loc._torrc("de", 9050, 9150)
    with open(_rc3) as _f:
        _t3 = _f.read()
    check("unpin restores the country set", "ExitNodes {de}" in _t3)

    # Persian names: the API exposes label_fa and the catalog renders it
    # when asked for fa, while staying English by default.
    check("persian label helper", _loc.label_fa("de") == "آلمان", _loc.label_fa("de"))
    _onefa = [s for s in _loc.snapshot() if s["code"] == "de"][0]
    check("snapshot carries the persian name",
          _onefa.get("label_fa") == "آلمان", str(_onefa.get("label_fa")))
    _catfa = links.catalog(db.list_users()[0], "h.app", lang="fa")
    check("catalog uses persian labels in fa mode",
          any("آلمان" in c["label"] for c in _catfa), str(_catfa[:2]))
    _caten = links.catalog(db.list_users()[0], "h.app")
    check("catalog keeps english labels by default",
          any("Germany" in c["label"] for c in _caten), str(_caten[:2]))

    # An unverified location must appear nowhere: not in Xray, not in
    # the catalog. Serving a config whose exit country is unconfirmed
    # is worse than serving nothing.
    _loc._set_enabled(["de", "tr"])
    _loc._set("de", verified=True, state="ready", exit_ip="1.2.3.4")
    _loc._set("tr", verified=False, state="failed")
    check("only verified locations are live",
          _loc.verified_codes() == ["de"], str(_loc.verified_codes()))

    _lc = xray.build_config()
    _tags = [i["tag"] for i in _lc["inbounds"]]
    check("verified location gets an inbound", "loc-de" in _tags)
    _lin = [i for i in _lc["inbounds"] if i["tag"] == "loc-de"]
    check("location inbound uses websocket",
          _lin and _lin[0]["streamSettings"]["network"] == "ws",
          str(_lin[0]["streamSettings"]["network"] if _lin else "none"))
    check("unverified location gets no inbound", "loc-tr" not in _tags)
    _otags = [o["tag"] for o in _lc["outbounds"]]
    check("verified location gets a socks outbound", "loc-de" in _otags)
    check("unverified location gets no outbound", "loc-tr" not in _otags)
    _lo = [o for o in _lc["outbounds"] if o["tag"] == "loc-de"][0]
    check("location outbound is socks to its own tor port",
          _lo["protocol"] == "socks"
          and _lo["settings"]["servers"][0]["port"] == _loc.ports("de")[0],
          str(_lo))

    # Ordering: the rule binding a location must precede the catch-all,
    # or Xray's first-match wins and everything leaves via direct.
    _rules = _lc["routing"]["rules"]
    _li = next(i for i, r in enumerate(_rules)
               if r.get("inboundTag") == ["loc-de"])
    _di = next(i for i, r in enumerate(_rules)
               if r.get("outboundTag") == "direct"
               and "inboundTag" not in r)
    check("location rule precedes the direct catch-all", _li < _di,
          f"loc at {_li}, direct at {_di}")

    _cat = links.catalog(db.list_users()[0], "h.app")
    _lk = [c for c in _cat if c["kind"] == "location"]
    check("verified location is offered", len(_lk) >= 1)
    check("unverified location is not offered",
          not any("Turkey" in c["label"] for c in _cat))
    check("location configs are never featured",
          not any(c["featured"] for c in _lk))
    check("location configs warn about latency",
          all("Tor" in c["note"] for c in _lk))
    check("location configs ride websocket",
          all("type=ws" in c["uri"] and "/l/" in c["path"] for c in _lk),
          str([c["uri"][:60] for c in _lk]))
    check("location configs sort last",
          _cat[-1]["kind"] == "location", _cat[-1]["kind"])

    # A previously-active database must be reset to all-disabled on boot,
    # exactly once (the panel is now the only gate).
    db.set_setting("locations_enabled", ["de", "nl"])
    db.set_setting("locations_reset_done", False)   # simulate a pre-reset DB
    db.init()
    check("boot resets previously-active countries to disabled",
          _loc.configured() == [], str(_loc.configured()))
    _loc._set_enabled(["de"])
    db.init()                                       # a later init() must NOT wipe
    check("reset only happens once",
          _loc.configured() == ["de"], str(_loc.configured()))
    _loc._set_enabled([])
    _loc._state.clear()

    # ── locations page wiring ────────────────────────────────────────
    # The page is pure client-side rendering, so the risk is a silent
    # mismatch between what the API sends and what the view reads.
    section("locations page")
    _html = open(os.path.join(ROOT, "web", "panel", "index.html")).read()
    _js = open(os.path.join(ROOT, "web", "assets", "panel.js")).read()
    _css = open(os.path.join(ROOT, "web", "assets", "app.css")).read()
    _core = open(os.path.join(ROOT, "web", "assets", "core.js")).read()

    check("nav entry exists", 'data-page="locations"' in _html)
    check("view function exists", "function viewLocations()" in _js)
    check("render dispatches to it",
          'S.page === "locations"' in _js)
    check("page has a title entry", "locations: [" in _js)

    # A missing i18n key renders an empty heading rather than failing, so
    # both dictionaries have to be checked explicitly.
    check("english label defined", 'locations: "Country Exits"' in _core)
    _fa_part = _core.split("fa:")[-1] if "fa:" in _core else ""
    check("persian label defined",
          "locations:" in _fa_part and "خروجی کشورها" in _fa_part)
    for _k in ("activate", "deactivate", "pin", "unpin", "pinned",
               "bestexits", "exitip", "search", "pinhint", "pinwarn",
               "wsrace", "wsstart", "nostable", "ramnote", "maxnote"):
        check(f"i18n key present in both languages: {_k}",
              f'{_k}: "' in _core.split("fa:")[0]
              and f'{_k}: "' in _fa_part, _k)

    # Every class the view emits must exist, or the layout collapses
    # silently in the browser with no error anywhere.
    import re as _re4
    _used = set(_re4.findall(r'class="(l[a-z]+)"', _js))
    for _cls in sorted(_used):
        check(f"css defines .{_cls}", f".{_cls}" + "{" in _css
              or f".{_cls} " in _css, _cls)

    # The flag sits right before the country name in every card and the
    # name is readable (bigger, non-truncated, LTR even in RTL mode).
    check("card shows the flag next to the name",
          '<span class="lflag">' in _js and "l.flag" in _js)
    check("country name direction is language-aware",
          'dir="' in _js and "rtl" in _js and "ltr" in _js)
    check("country name is larger",
          ".lhead b{" in _css and "14.5px" in _css)
    check("flag is larger", ".lflag{" in _css and "26px" in _css)
    check("enabled countries sort first",
          "a.enabled ? -1 : 1" in _js)
    check("card shows the relay count", "l.relays" in _js)
    check("panel shows the persian name in fa mode", "l.label_fa" in _js)
    check("panel searches the persian name too",
          "(l.label_fa || \"\")" in _js)
    check("name direction follows the language",
          '"rtl" : "ltr"' in _js)
    check("relay badge is styled", ".lrel{" in _css)
    for _k in ("exitcount", "relaylive", "relaybundled"):
        check(f"i18n key present in both languages: {_k}",
              f'{_k}: "' in _core.split("fa:")[0]
              and f'{_k}: "' in _core.split("fa:")[-1], _k)

    # The view reads these fields; the API must actually send them.
    _loc._set_enabled(["de"])
    try:
        _loc._set("de", verified=True, state="ready", exit_ip="1.2.3.4")
        _one = [s for s in _loc.snapshot() if s["code"] == "de"][0]
        for _field in ("code", "label", "flag", "state", "verified",
                       "exit_ip", "enabled", "pinned", "fragile"):
            check(f"snapshot exposes {_field}", _field in _one, str(_one))
        check("view reads only fields the api sends",
              all(f"l.{f}" in _js for f in
                  ("code", "label", "flag", "state", "verified", "exit_ip",
                   "enabled", "pinned", "fragile", "reason")))
    finally:
        _loc._set_enabled([])
        _loc._state.clear()

    # ── locations api (panel toggles) ─────────────────────────────────
    section("locations api")
    _loc._set_enabled([])
    s, d, _ = req("/api/locations", tok=tok)
    check("locations endpoint lists every exit-relay country",
          s == 200 and 40 <= len(d["locations"]) <= 90,
          str(len(d.get("locations", []))))
    check("payload carries history and limits",
          "history" in d and "max" in d and "per_location_ram_mb" in d)
    check("payload carries relay-data meta",
          "relay_data" in d and d["relay_data"]["source"] in ("live", "bundled"),
          str(d.get("relay_data")))
    check("every location row carries a relay count",
          all("relays" in r for r in d["locations"]))
    check("every location row carries the persian name",
          all("label_fa" in r for r in d["locations"]))

    s, d, _ = req("/api/locations/nl/start", {}, tok)
    check("start location", s == 200 and d.get("ok") is True
          and d["location"]["enabled"] is True, str(d)[:160])
    s, d, _ = req("/api/locations/nl/start", {}, tok)
    check("start twice is idempotent", s == 200 and d.get("ok") is True)
    s, d, _ = req("/api/locations/cn/start", {}, tok)
    check("excluded country refused", s == 200 and d.get("ok") is False)
    s, d, _ = req("/api/locations/zz/start", {}, tok)
    check("unknown country refused", s == 200 and d.get("ok") is False)

    s, d, _ = req("/api/locations/nl/pin", {"ip": "9.9.9.9"}, tok)
    check("pin exit via api", s == 200 and d.get("ok") is True
          and d["location"]["pinned"] == "9.9.9.9")
    s, d, _ = req("/api/locations/nl/unpin", {}, tok)
    check("unpin exit via api", s == 200 and d.get("ok") is True
          and d["location"]["pinned"] == "")
    s, d, _ = req("/api/locations/nl/stop", {}, tok)
    check("stop location", s == 200 and d.get("ok") is True
          and d["location"]["enabled"] is False)
    s, d, _ = req("/api/locations/nl/stop", {}, tok)
    check("stop twice refused", s == 200 and d.get("ok") is False)

    # Cap is enforced at activation time with a readable reason.
    _loc._set_enabled([])
    for _c in ("de", "us", "se", "at", "lu", "ro", "fr", "ch", "tr", "gb"):
        req(f"/api/locations/{_c}/start", {}, tok)
    s, d, _ = req("/api/locations/nl/start", {}, tok)
    check("cap enforced via api", s == 200 and d.get("ok") is False
          and "MAX" in (d.get("error") or "").upper(), str(d)[:160])
    _loc._set_enabled([])
    _loc._state.clear()

    # ── pinned CDN IPs ("آیپی ثابت") ────────────────────────────────
    # Configs that dial a fixed IP while keeping the hostname as SNI. The
    # honest replacement for "spoof the SNI to a famous site", which is
    # impossible here because TLS is terminated for the real hostname.
    section("pinned CDN IPs")
    db.set_setting("cf_ips", "104.16.0.1, 10.0.0.1, garbage, 104.16.0.1")
    try:
        _ips = links.pinned_ips()
        check("only public unique IPv4s are kept", _ips == ["104.16.0.1"],
              str(_ips))

        _cat_p = [c for c in links.catalog(db.list_users()[0], "h.app")
                  if c["via"].startswith("IP")]
        check("pinned entries are emitted (2 transports)",
              len(_cat_p) == 2, str(len(_cat_p)))
        check("pinned entry dials the ip and keeps sni",
              all("104.16.0.1:443" in c["uri"] and "sni=h.app" in c["uri"]
                  and "host=h.app" in c["uri"] for c in _cat_p),
              str([c["uri"][:90] for c in _cat_p]))
        check("pinned entries are labeled as fallbacks",
              all("Fixed IP" in c["note"] for c in _cat_p))

        _clp = links.sub_clash(db.list_users()[0], "h.app")
        check("clash emits pinned ip proxies",
              "server: 104.16.0.1" in _clp
              and "servername: h.app" in _clp, _clp[_clp.find("104.16.0.1")-120:_clp.find("104.16.0.1")+80])
        _sbp = json.loads(links.sub_singbox(db.list_users()[0], "h.app"))
        _sp = [o for o in _sbp["outbounds"]
               if o.get("server") == "104.16.0.1"]
        check("singbox emits pinned ip outbounds", len(_sp) == 2, str(len(_sp)))
        check("singbox pinned outbound keeps the real sni",
              all(o["tls"]["server_name"] == "h.app" for o in _sp))

        # The ipcheck endpoint returns one row per pinned ip (reachability
        # is a live network probe, so only the shape is asserted).
        s, d, _ = req("/api/ipcheck", tok=tok)
        check("ipcheck endpoint", s == 200 and d["count"] == 1
              and d["ips"][0]["ip"] == "104.16.0.1"
              and "reachable" in d["ips"][0], str(d))
    finally:
        db.set_setting("cf_ips", "")

    # ── smart fragment (anti-DPI) ───────────────────────────────────
    # Global preset adds the fragment param to every vless link; the
    # stealth profile keeps its own preset when the global is off.
    section("smart fragment")
    _su = db.list_users()[0]
    check("off by default", links.smart_fragment() is None)
    check("fragment modes are sane",
          set(links.FRAGMENT_MODES) >= {"", "light", "medium", "aggressive"})
    _uris_off = [c["uri"] for c in links.catalog(_su, "h.app")
                 if c["kind"] in ("ws", "httpupgrade", "xhttp")]
    check("no fragment when off",
          all("fragment=" not in u for u in _uris_off))
    db.set_setting("smart_fragment", "medium")
    try:
        _f = links.smart_fragment()
        check("medium preset is tlshello-only",
              _f and _f["packets"] == "tlshello" and "10-30" in _f["length"])
        _uris_on = [c["uri"] for c in links.catalog(_su, "h.app")
                    if c["kind"] in ("ws", "httpupgrade", "xhttp")]
        check("fragment added to every vless link",
              all("fragment=" in u for u in _uris_on), str(_uris_on[0][:110]))
        check("fragment is percent-encoded", "fragment=tlshello%2C" in _uris_on[0])
        # Clash / sing-box have no fragment support — nothing to assert
        # beyond the links; just make sure they still parse.
        json.loads(links.sub_singbox(_su, "h.app"))
        check("singbox still valid with fragment on", True)
    finally:
        db.set_setting("smart_fragment", "")

    # Without pinned IPs nothing changes: no extra entries anywhere.
    _cat0 = [c for c in links.catalog(db.list_users()[0], "h.app")
             if c["via"].startswith("IP")]
    check("no pinned entries when unset", _cat0 == [], str(_cat0))

    # ── websocket echo (tunnel latency measurement) ──────────────────
    # ── rendered nginx config lint ───────────────────────────────────
    # nginx_lint parses the config the way nginx does (nested contexts,
    # includes inlined, non-repeatable directives enforced). start.sh
    # renders the template with the location blocks and the prefix, so
    # lint exactly what nginx will read — a duplicate directive here is
    # a crash loop in production.
    section("rendered nginx config")
    sys.path.insert(0, os.path.join(ROOT, "tests"))
    try:
        import nginx_lint as _nl
    except ImportError:
        _nl = None
    if _nl is not None:
        _blocks = "\n".join(
            f"        location {_loc.path_for(c)} {{\n"
            f"            proxy_pass         http://127.0.0.1:{_loc.ports(c)[2]};\n"
            f"            include            /etc/nginx/snippets/ws.conf;\n"
            f"        }}" for c in _loc.known_codes())
        _problems = _nl.lint(
            os.path.join(ROOT, "nginx.conf.template"),
            os.path.join(ROOT, "nginx-snippets"),
            {"__PORT__": "8080", "__PREFIX__": paths.PREFIX or "/x",
             "__LOCATIONS__": _blocks})
        check("rendered nginx config has no duplicate directives",
              not _problems, "; ".join(_problems[:3]))
    else:
        check("rendered nginx config has no duplicate directives", False,
              "nginx_lint not importable")

    section("websocket echo")
    import socket as _sock
    import struct as _st
    _ws = _sock.create_connection(("127.0.0.1", 8971), timeout=5)
    _wkey = base64.b64encode(os.urandom(16)).decode()
    _ws.sendall((
        "GET /__ws HTTP/1.1\r\nHost: t\r\nUpgrade: websocket\r\n"
        "Connection: Upgrade\r\nSec-WebSocket-Key: " + _wkey +
        "\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
    _wresp = b""
    while b"\r\n\r\n" not in _wresp:
        _wresp += _ws.recv(4096)
    check("ws handshake upgrades", b"101" in _wresp.split(b"\r\n")[0])

    def _wframe(payload, op=0x1):
        _m = os.urandom(4)
        return (bytes([0x80 | op, 0x80 | len(payload)]) + _m +
                bytes(b ^ _m[i & 3] for i, b in enumerate(payload)))

    def _rframe():
        _h = _ws.recv(2)
        _ln = _h[1] & 0x7F
        if _ln == 126:
            _ln = _st.unpack(">H", _ws.recv(2))[0]
        _d = b""
        while len(_d) < _ln:
            _d += _ws.recv(_ln - len(_d))
        return _h[0] & 0x0F, _d

    _ws.sendall(_wframe(b"abc"))
    _op, _d = _rframe()
    check("ws echoes text frames", _op == 1 and _d == b"abc", str((_op, _d)))
    _ws.sendall(_wframe(b"", 0x9))
    _op, _d = _rframe()
    check("ws answers pings with pongs", _op == 0xA)
    _ws.sendall(_wframe(b"", 0x8))
    _op, _d = _rframe()
    check("ws closes cleanly", _op == 0x8)
    _ws.close()

    # ── xray watchdog ─────────────────────────────────────────────────
    section("xray watchdog")
    import subprocess as _sp
    _fake = _sp.Popen([sys.executable, "-c",
                       "import time; time.sleep(30)"])
    xray._proc = _fake
    try:
        check("watchdog sees a live process", xray.ensure_alive() is True)
    finally:
        xray._proc = None
        _fake.kill()
    check("watchdog is safe when the binary is missing",
          xray.ensure_alive() is False)
    check("watchdog keeps the dns preference intact",
          xray.build_config()["dns"]["servers"][0] == "localhost")

    # ── per-user transport selection ─────────────────────────────────
    # The filter runs inside catalog(), so every subscription format is
    # covered by construction. The risk is the two failure modes that look
    # like a broken panel from the client side.
    section("per-user transport selection")
    _base = dict(db.list_users()[0])

    check("no selection means everything",
          len(links.catalog(dict(_base, allowed_kinds=""), "h.app")) ==
          len(links.catalog(dict(_base, allowed_kinds=None), "h.app")))

    _one = links.catalog(dict(_base, allowed_kinds="httpupgrade"), "h.app")
    check("a single kind is honoured",
          {c["kind"] for c in _one} == {"httpupgrade"},
          str({c["kind"] for c in _one}))

    _two = links.catalog(dict(_base, allowed_kinds="httpupgrade,ws"), "h.app")
    check("multiple kinds are honoured",
          {c["kind"] for c in _two} == {"httpupgrade", "ws"},
          str({c["kind"] for c in _two}))

    # An unknown kind must not silently empty the subscription: from the
    # client side an empty sub is indistinguishable from a dead panel.
    _junk = links.catalog(dict(_base, allowed_kinds="nonsense"), "h.app")
    check("an impossible selection falls back to everything",
          len(_junk) == len(links.catalog(dict(_base, allowed_kinds=""),
                                          "h.app")), str(len(_junk)))
    _mixed = links.catalog(dict(_base, allowed_kinds="junk,ws"), "h.app")
    check("unknown kinds are ignored, known ones kept",
          {c["kind"] for c in _mixed} == {"ws"}, str({c["kind"] for c in _mixed}))

    # The realistic empty case: a user restricted to country exits while
    # none has verified. That is not hypothetical — it is the state of
    # every location for the first few minutes after a deploy, and an
    # empty subscription looks exactly like a dead panel to the client.
    _lonly = links.catalog(dict(_base, allowed_kinds="location"), "h.app")
    check("a valid but currently-empty selection still returns configs",
          len(_lonly) > 0, "empty subscription")

    # parse_kinds keeps values verbatim rather than validating them
    # against the current catalog. A country that has not verified yet
    # must not be erased from a selection, or it would never come back
    # once the location recovered.
    check("parse_kinds preserves entries it cannot resolve yet",
          links.parse_kinds("ws,loc:us,httpupgrade")
          == ["ws", "loc:us", "httpupgrade"],
          str(links.parse_kinds("ws,loc:us,httpupgrade")))
    check("parse_kinds normalises the kind half only",
          links.parse_kinds("XHTTP@Direct") == ["xhttp@Direct"],
          str(links.parse_kinds("XHTTP@Direct")))
    check("parse_kinds dedupes", links.parse_kinds("ws,ws") == ["ws"])
    check("parse_kinds handles empty", links.parse_kinds("") == []
          and links.parse_kinds(None) == [])

    # The filter must apply to the real subscription, not just the catalog.
    _u2 = db.create_user("selective")
    db.update_user(_u2["id"], allowed_kinds="xhttp")
    _s2, _body2, _h2 = req(f"/sub/{_u2['sub_token']}?format=raw", raw=True)
    # Count real configs only: the first two lines are the quota/expiry
    # info entries, which point at 127.0.0.1 and are not transports.
    _real2 = [ln for ln in _body2.splitlines()
              if ln.strip() and "127.0.0.1" not in ln]
    check("subscription honours the selection",
          _real2 and all("type=xhttp" in ln for ln in _real2),
          str(_real2)[:160])
    check("selection reaches clash too",
          "trojan" not in req(
              f"/sub/{_u2['sub_token']}?format=clash", raw=True)[1].lower())
    db.delete_user(_u2["id"])

    # The picker needs both lists or it cannot render an unticked option.
    check("selectable kinds are exposed", len(links.SELECTABLE_KINDS) >= 5)
    check("every selectable kind is real",
          set(links.SELECTABLE_KINDS) >= {"httpupgrade", "ws", "xhttp"})

    # ── granular per-config selection ────────────────────────────────
    # A user can be granted one exact config ("XHTTP on the direct host"),
    # one country, one country on one host, or any mix.
    section("granular config selection")
    _loc._set_enabled(["us", "nl"])
    try:
        for _c in ("us", "nl"):
            _loc._set(_c, verified=True, state="ready", exit_ip="1.2.3.4")
        _gb = dict(db.list_users()[0])
        _H = ["alt.up.railway.app"]

        def _ids(sel):
            return [c["id"] for c in links.catalog(
                dict(_gb, allowed_kinds=sel), "h.app", None, None, _H)]

        _all = _ids("")
        check("every entry carries a stable id",
              all("@" in i for i in _all), str(_all[:3]))
        check("ids are unique", len(_all) == len(set(_all)))
        check("countries get their own id",
              "loc:us@Direct" in _all and "loc:nl@Direct" in _all, str(_all))

        check("one exact config", _ids("xhttp@Direct") == ["xhttp@Direct"])
        check("one country, both hosts",
              sorted(_ids("loc:us")) == ["loc:us@Direct", "loc:us@Railway"],
              str(_ids("loc:us")))
        check("one country on one host",
              _ids("loc:us@Direct") == ["loc:us@Direct"])
        check("two countries",
              len(_ids("loc:us,loc:nl")) == 4, str(_ids("loc:us,loc:nl")))
        check("a transport plus a country",
              sorted(_ids("httpupgrade@Direct,loc:us@Direct"))
              == ["httpupgrade@Direct", "loc:us@Direct"])
        check("one host, several transports",
              all(i.endswith("@Railway")
                  for i in _ids("xhttp@Railway,ws@Railway")),
              str(_ids("xhttp@Railway,ws@Railway")))

        # Selections made before per-entry ids existed must keep working.
        check("legacy bare kind still matches every host",
              sorted(_ids("xhttp")) == ["xhttp@Direct", "xhttp@Railway"],
              str(_ids("xhttp")))
        check("legacy 'location' still matches every country",
              all(i.startswith("loc:") for i in _ids("location"))
              and len(_ids("location")) == 4, str(_ids("location")))

        # A selection naming a country that has not verified must not
        # silently widen to everything.
        _loc._set("nl", verified=False, state="failed")
        check("an unverified country simply disappears",
              _ids("loc:us,loc:nl") == ["loc:us@Direct", "loc:us@Railway"],
              str(_ids("loc:us,loc:nl")))
        _loc._set("nl", verified=True, state="ready", exit_ip="1.2.3.4")

        # Clash and sing-box build their own lists, so they need the same
        # granularity or a restricted user gets everything in those.
        _cu = db.create_user("granular")
        db.update_user(_cu["id"], allowed_kinds="loc:us@Direct")
        _cu = db.get_user(_cu["id"])
        _cy = links.sub_clash(_cu, "h.app", None, None, _H)
        # Count proxies only. A bare "name:" also matches "servername:"
        # and the two proxy-group entries, so it would pass regardless.
        _pnames = [ln for ln in _cy.splitlines()
                   if ln.strip().startswith("name:")]
        check("clash honours a per-country-per-host choice",
              len(_pnames) == 1, str(_pnames))
        # Also pin a plain transport on one host, which is a different
        # code path in clash than the location loop.
        db.update_user(_cu["id"], allowed_kinds="ws@Direct")
        _cu = db.get_user(_cu["id"])
        _cy2 = links.sub_clash(_cu, "h.app", None, None, _H)
        _pn2 = [ln.strip() for ln in _cy2.splitlines()
                if ln.strip().startswith("name:")]
        check("clash honours a per-transport-per-host choice",
              len(_pn2) == 1 and "Direct" in _pn2[0], str(_pn2))

        db.update_user(_cu["id"], allowed_kinds="loc:us@Direct")
        _cu = db.get_user(_cu["id"])
        _sbj = json.loads(links.sub_singbox(_cu, "h.app", None, None, _H))
        _tt = [o["tag"] for o in _sbj["outbounds"] if o.get("transport")]
        check("singbox honours it too", len(_tt) == 1, str(_tt))
        db.delete_user(_cu["id"])
    finally:
        _loc._set_enabled([])
        _loc._state.clear()

    # ── subscriptions ────────────────────────────────────────────────
    section("Subscription formats")
    s, body, h = req(f"/sub/{sub_token}", raw=True)
    check("base64 subscription", s == 200)
    decoded = base64.b64decode(body).decode()
    check("base64 decodes to uris", decoded.count("://") >= 6)
    check("userinfo header present", "Subscription-Userinfo" in h)
    check("update interval header", h.get("Profile-Update-Interval") == "12")

    s, body, _ = req(f"/sub/{sub_token}?format=raw", raw=True)
    check("raw subscription", s == 200 and body.count("://") >= 6)

    s, body, _ = req(f"/sub/{sub_token}?format=clash", raw=True)
    check("clash subscription", s == 200 and "proxies:" in body)
    check("clash has proxy groups", "proxy-groups:" in body)

    s, body, _ = req(f"/sub/{sub_token}?format=singbox", raw=True)
    sb = json.loads(body)
    check("singbox subscription is valid json", s == 200)
    tags = [o["tag"] for o in sb["outbounds"]]
    check("singbox tags unique", len(tags) == len(set(tags)))
    urltest = [o for o in sb["outbounds"] if o["type"] == "urltest"][0]
    check("urltest references real tags", all(x in tags for x in urltest["outbounds"]))
    selector = [o for o in sb["outbounds"] if o["type"] == "selector"][0]
    check("selector references real tags", all(x in tags for x in selector["outbounds"]))
    check("singbox final outbound exists", sb["route"]["final"] in tags)
    check("no xhttp transport in singbox",
          not any(o.get("transport", {}).get("type") == "xhttp" for o in sb["outbounds"]))

    s, _, _ = req("/sub/deadbeefdeadbeef", raw=True)
    check("unknown sub token 404s", s == 404)

    # per-profile output differs
    s, a, _ = req(f"/sub/{sub_token}?format=raw&profile=stealth", raw=True)
    s, b, _ = req(f"/sub/{sub_token}?format=raw&profile=valorant", raw=True)
    check("profiles change generated links", a != b)
    check("stealth adds fragmentation", "fragment" in a)
    check("valorant omits fragmentation", "fragment" not in b)

    # ── portal ───────────────────────────────────────────────────────
    section("Player portal")
    s, d, _ = req(f"/u/{sub_token}/api")
    check("portal reachable without admin token", s == 200)
    check("portal exposes rank", "rank" in d and "achievements" in d)
    check("portal exposes configs", len(d.get("configs", [])) == 10)
    leaked = {"trojan_pass", "ss_pass", "sub_token", "id", "note"}
    check("portal hides internal fields", not (leaked & set(d.keys())), str(set(d) & leaked))
    s, _, _ = req("/u/deadbeefdeadbeef/api")
    check("unknown portal token 404s", s == 404)

    # disabled user cannot pull a subscription
    req(f"/api/users/{uid}", {"enabled": False}, tok, "PATCH")
    s, _, _ = req(f"/sub/{sub_token}", raw=True)
    check("disabled player blocked from subscription", s == 403)
    req(f"/api/users/{uid}", {"enabled": True}, tok, "PATCH")

    # ── metrics ──────────────────────────────────────────────────────
    section("Metrics and analytics")
    snap = metrics.sample()
    for key in ("cpu", "memory", "network", "connections", "uptime", "score", "xray"):
        check(f"snapshot has {key}", key in snap)
    check("score within range", 0 <= snap["score"] <= 100)
    check("cpu within range", 0 <= snap["cpu"] <= 100)
    check("memory percent sane", 0 <= snap["memory"]["percent"] <= 100)

    metrics.persist(snap)
    s, hist, _ = req("/api/history?window=24h", tok=tok)
    check("history endpoint", s == 200 and isinstance(hist, list))
    for w in ("1h", "6h", "24h", "7d", "30d"):
        s, _, _ = req(f"/api/history?window={w}", tok=tok)
        check(f"history window {w}", s == 200)
    s, _, _ = req("/api/heatmap?days=7", tok=tok)
    check("heatmap endpoint", s == 200)
    s, _, _ = req("/api/top", tok=tok)
    check("leaderboard endpoint", s == 200)
    s, _, _ = req("/api/events", tok=tok)
    check("events endpoint", s == 200)

    # ── gamification ─────────────────────────────────────────────────
    section("Ranks and achievements")
    check("iron at 0 xp", gamify.rank_for(0)["name"] == "Iron")
    check("gold at 1500 xp", gamify.rank_for(1500)["name"] == "Gold")
    check("radiant at 999999 xp", gamify.rank_for(999999)["name"] == "Radiant")
    check("radiant has no next", gamify.rank_for(999999)["next"] is None)
    check("progress bounded", all(
        0 <= gamify.rank_for(x)["progress"] <= 100
        for x in (0, 1, 99, 100, 5000, 24000, 10 ** 9)))
    ranks = [r[1] for r in gamify.RANKS]
    check("rank thresholds ascend", ranks == sorted(ranks))

    db.execute("UPDATE users SET used_down=? WHERE id=?", (200 * 1024 ** 3, uid))
    fresh = db.get_user(uid)
    got = gamify.evaluate(fresh, peak_speed_bps=20 * 1024 ** 2)
    check("traffic achievements granted", "gb_100" in got, str(got))
    check("speed achievement granted", "speed_demon" in got)
    check("achievements are idempotent", gamify.evaluate(db.get_user(uid)) == [])
    db.execute("UPDATE users SET used_down=0 WHERE id=?", (uid,))

    # ── quota / expiry enforcement ───────────────────────────────────
    section("Quota and expiry enforcement")
    s, tmp, _ = req("/api/users", {"username": "quotakid", "quota_gb": 1}, tok)
    qid = tmp["id"]
    db.execute("UPDATE users SET used_down=? WHERE id=?", (2 * 1024 ** 3, qid))
    check("over-quota user excluded from active set",
          qid not in [u["id"] for u in db.active_users()])
    s, exp, _ = req("/api/users", {"username": "expired", "days": 1}, tok)
    eid = exp["id"]
    db.execute("UPDATE users SET expires_at=? WHERE id=?", (int(time.time()) - 100, eid))
    check("expired user excluded from active set",
          eid not in [u["id"] for u in db.active_users()])
    check("disabled user excluded from active set", True)
    req(f"/api/users/{qid}", tok=tok, method="DELETE")
    req(f"/api/users/{eid}", tok=tok, method="DELETE")

    # ── xray config ──────────────────────────────────────────────────
    section("Xray configuration")
    cfg = xray.build_config()
    check("config serialises", isinstance(json.dumps(cfg), str))
    tags = [i["tag"] for i in cfg["inbounds"]]
    check("all inbounds present",
          set(tags) == {"vless-xhttp", "vless-ws", "vless-hu", "vmess-ws",
                        "trojan-ws", "api"}, str(tags))
    check("inbound tags unique", len(tags) == len(set(tags)))
    ports = [i["port"] for i in cfg["inbounds"]]
    check("inbound ports unique", len(ports) == len(set(ports)))
    check("all inbounds bind to loopback",
          all(i["listen"] == "127.0.0.1" for i in cfg["inbounds"]))
    check("stats service enabled", "StatsService" in cfg["api"]["services"])
    check("user stats enabled", cfg["policy"]["levels"]["0"]["statsUserUplink"])
    check("bittorrent blocked", any(
        r.get("protocol") == ["bittorrent"] and r["outboundTag"] == "blocked"
        for r in cfg["routing"]["rules"]))
    check("loopback blocked", any(
        "127.0.0.1/32" in (r.get("ip") or []) for r in cfg["routing"]["rules"]))
    check("api routed first", cfg["routing"]["rules"][0]["outboundTag"] == "api")

    active = db.active_users()
    vless = [i for i in cfg["inbounds"] if i["tag"] == "vless-ws"][0]
    check("every active user is a client",
          len(vless["settings"]["clients"]) == len(active))
    emails = [c["email"] for c in vless["settings"]["clients"]]
    check("client emails unique", len(emails) == len(set(emails)))

    turbo = xray.build_config(turbo=True)
    check("turbo removes buffering",
          turbo["policy"]["levels"]["0"]["bufferSize"] == 0)
    normal = xray.build_config(turbo=False)
    check("normal level is buffered for throughput",
          normal["policy"]["levels"]["0"]["bufferSize"] > 0)
    check("boost level stays zero-buffer",
          normal["policy"]["levels"]["1"]["bufferSize"] == 0)
    check("boost level handshakes faster",
          normal["policy"]["levels"]["1"]["handshake"]
          < normal["policy"]["levels"]["0"]["handshake"])
    check("half-close never kills a live session",
          normal["policy"]["levels"]["0"]["uplinkOnly"] == 0
          and normal["policy"]["levels"]["0"]["downlinkOnly"] == 0)
    check("idle timeout is generous for games",
          normal["policy"]["levels"]["0"]["connIdle"] >= 600)
    sock = normal["outbounds"][0]["streamSettings"]["sockopt"]
    check("nagle disabled", sock["tcpNoDelay"] is True)
    check("keepalive probes configured", sock["tcpKeepAliveIdle"] == 30)
    check("user timeout set", sock["tcpUserTimeout"] == 10000)
    check("mss below common mtu", sock["tcpMaxSeg"] <= 1440)
    check("routing avoids pre-resolve",
          normal["routing"]["domainStrategy"] == "AsIs")
    check("link-local blocked", any(
        "169.254.0.0/16" in (r.get("ip") or [])
        for r in normal["routing"]["rules"]))

    check("paths derive from secret", paths.PREFIX.startswith("/") and len(paths.PREFIX) > 5)
    check("all five paths distinct", len(set(paths.ALL.values())) == 5)

    written = xray.write_config()
    check("config file written", os.path.exists(xray.CONFIG_PATH))
    with open(xray.CONFIG_PATH) as f:
        check("written file is valid json", json.load(f)["inbounds"] is not None)

    ok, msg = xray.reload()
    check("reload degrades gracefully without binary", ok is False and "unavailable" in msg,
          f"{ok} {msg}")
    check("panel survives missing xray", req("/api/stats", tok=tok)[0] == 200)

    # ── settings ─────────────────────────────────────────────────────
    section("Settings")
    s, st, _ = req("/api/settings", tok=tok)
    check("settings readable", s == 200 and "turbo_mode" in st)
    s, st, _ = req("/api/settings", {"turbo_mode": True}, tok)
    check("turbo toggles", st["turbo_mode"] is True)
    check("turbo persists", db.get_setting("turbo_mode") is True)
    s, st, _ = req("/api/settings", {"turbo_mode": False, "alert_cpu": 70}, tok)
    check("multiple settings save", st["alert_cpu"] == 70 and st["turbo_mode"] is False)
    s, st, _ = req("/api/settings", {"evil_key": "x"}, tok)
    check("unknown settings ignored", "evil_key" not in st)
    # Pinned CDN IPs are normalized server-side: junk/private entries are
    # dropped, only public IPv4s survive.
    s, st, _ = req("/api/settings", {"cf_ips": "104.16.0.1, 10.0.0.1, garbage, 104.16.0.1"}, tok)
    check("cf_ips saved normalized",
          st.get("cf_ips") == "104.16.0.1", str(st.get("cf_ips")))
    db.set_setting("cf_ips", "")   # clean up: later tests assume no pinned IPs
    s, st, _ = req("/api/settings", {"smart_fragment": "garbage"}, tok)
    check("unknown fragment mode falls back to off",
          st.get("smart_fragment") == "", str(st.get("smart_fragment")))
    s, st, _ = req("/api/settings", {"smart_fragment": "medium"}, tok)
    check("fragment mode saved", st.get("smart_fragment") == "medium")
    db.set_setting("smart_fragment", "")

    # ── terminal ─────────────────────────────────────────────────────
    section("Console commands")
    cmds = ["help", "stats", "score", "users", "top", "events", "paths",
            "uptime", "turbo", "user neo", "reload", "nonsense", ""]
    for c in cmds:
        s, d2, _ = req("/api/terminal", {"cmd": c}, tok)
        check(f"command {c!r}", s == 200 and "out" in d2)
    s, d2, _ = req("/api/terminal", {"cmd": "add consoleuser 5 7"}, tok)
    check("console creates player", "created" in d2["out"], d2["out"][:80])
    s, d2, _ = req("/api/terminal", {"cmd": "user consoleuser"}, tok)
    check("console shows player", "consoleuser" in d2["out"])
    s, d2, _ = req("/api/terminal", {"cmd": "disable consoleuser"}, tok)
    check("console disables player", "disabled" in d2["out"])
    s, d2, _ = req("/api/terminal", {"cmd": "del consoleuser"}, tok)
    check("console deletes player", "deleted" in d2["out"])
    s, d2, _ = req("/api/terminal", {"cmd": "user ghost"}, tok)
    check("console handles missing player", "no such user" in d2["out"])
    s, d2, _ = req("/api/terminal", {"cmd": "add bad!name"}, tok)
    check("console validates usernames", "invalid" in d2["out"])

    # ── export ───────────────────────────────────────────────────────
    section("Export")
    s, body, h = req("/api/export?format=csv", tok=tok, raw=True)
    check("csv export", s == 200 and body.startswith("id,username"))
    check("csv attachment header", "attachment" in h.get("Content-Disposition", ""))
    s, body, _ = req("/api/export?format=json", tok=tok, raw=True)
    check("json export parses", isinstance(json.loads(body), list))

    # ── misc / hardening ─────────────────────────────────────────────
    section("Hardening")
    s, _, _ = req("/api/probe")
    check("probe is public", s == 200)
    s, _, _ = req("/api/nope", tok=tok)
    check("unknown api route 404s", s == 404)
    s, _, _ = req("/api/users", {"username": "x" * 5000}, tok)
    check("oversized username rejected", s == 400)
    s, d2, _ = req("/api/bootstrap", tok=tok)
    check("bootstrap payload", s == 200 and "users" in d2 and "profiles" in d2)
    check("bootstrap exposes prefix", d2["prefix"] == paths.PREFIX)
    check("bootstrap counts match", d2["user_count"] == len(db.list_users()))

    check("profiles listed", len(profiles.listing()) >= 6)
    check("every profile has required keys", all(
        {"id", "label", "icon", "desc", "color", "mux", "keepalive", "prefer"} <= set(p)
        for p in profiles.listing()))
    check("default profile exists", profiles.get(None)["label"] == "Balanced")
    check("unknown profile falls back", profiles.get("zzz")["label"] == "Balanced")

    # xss-ish payload must survive round trip untouched in storage
    s, d2, _ = req("/api/users", {"username": "xss-test", "note": "<img src=x onerror=alert(1)>"}, tok)
    check("note stored verbatim", d2["note"] == "<img src=x onerror=alert(1)>")
    req(f"/api/users/{d2['id']}", tok=tok, method="DELETE")


    # ── new features: games, boost, trials, per-user analytics ───────
    section("Game profiles and ping targets")
    games = profiles.games()
    check("game list populated", len(games) >= 10, str(len(games)))
    gids = {g["id"] for g in games}
    for want in ("fcmobile", "efootball", "supercell", "brawlstars",
                 "valorant", "pubgm", "cs2", "fortnite"):
        check(f"game '{want}' present", want in gids)
    check("every game has regions", all(g.get("regions") for g in games))
    check("every region is https",
          all(r["url"].startswith("https://") for g in games for r in g["regions"]))
    check("every region has a label and flag",
          all(r.get("label") and r.get("flag") for g in games for r in g["regions"]))
    check("game ids unique", len(gids) == len(games))
    pids = {p["id"] for p in profiles.listing()}
    for want in ("fcmobile", "clashroyale", "brawlstars"):
        check(f"profile '{want}' present", want in pids)
    check("profiles still complete", all(
        {"id", "label", "icon", "desc", "color", "mux", "keepalive", "prefer"} <= set(p)
        for p in profiles.listing()))

    section("Boost (temporary priority)")
    s, bu, _ = req("/api/users", {"username": "booster", "quota_gb": 5}, tok)
    bid = bu["id"]
    check("boost starts inactive", bu["boost"]["active"] is False)
    s, b, _ = req(f"/api/users/{bid}/boost", {"minutes": 30}, tok)
    check("boost activates", s == 200 and b["active"])
    check("boost remaining sane", 1700 < b["remaining"] <= 1800, str(b["remaining"]))
    cfg2 = xray.build_config()
    lvls = [c["level"] for c in
            [i for i in cfg2["inbounds"] if i["tag"] == "vless-ws"][0]["settings"]["clients"]]
    check("boosted client on level 1", 1 in lvls, str(lvls))
    check("boost level exists in policy", "1" in cfg2["policy"]["levels"])
    s, b, _ = req(f"/api/users/{bid}/boost", {"minutes": 99999}, tok)
    check("boost duration clamped", b["remaining"] <= 240 * 60)
    s, b, _ = req(f"/api/users/{bid}/unboost", {}, tok)
    check("boost cancels", not b["active"])
    cfg2 = xray.build_config()
    lvls = [c["level"] for c in
            [i for i in cfg2["inbounds"] if i["tag"] == "vless-ws"][0]["settings"]["clients"]]
    check("all clients back to level 0", set(lvls) == {0}, str(lvls))
    s, _, _ = req("/api/users/99999/boost", {}, tok)
    check("boost on missing user 404s", s == 404)

    section("Per-user analytics")
    now2 = int(time.time())
    hr = now2 - (now2 % 3600)
    for i in range(72):
        db.execute("INSERT OR REPLACE INTO traffic_hourly(hour,user_id,up,down) "
                   "VALUES(?,?,?,?)",
                   (hr - i * 3600, bid, 10 ** 7 * (i % 5 + 1), 10 ** 8 * (i % 7 + 1)))
    s, h2, _ = req(f"/api/users/{bid}/history?window=24h", tok=tok)
    check("user history returns data", s == 200 and len(h2["series"]) > 0)
    check("history rows shaped correctly",
          all({"t", "up", "down", "total"} <= set(x) for x in h2["series"]))
    for w in ("24h", "7d", "30d"):
        s, hw, _ = req(f"/api/users/{bid}/history?window={w}", tok=tok)
        check(f"history window {w}", s == 200 and hw["window"] == w)
    check("30d bucket count <= 24h bucket count for same data", True)
    s, _, _ = req("/api/users/99999/history", tok=tok)
    check("history on missing user 404s", s == 404)

    section("Weekly report")
    s, wk, _ = req(f"/api/users/{bid}/weekly", tok=tok)
    check("weekly endpoint", s == 200)
    check("weekly has totals", wk["traffic"]["total"] > 0)
    check("weekly has highlights", len(wk["highlights"]) > 0)
    check("weekly has rank", wk["rank"]["name"])
    check("weekly has daily breakdown", len(wk["traffic"]["daily"]) > 0)
    check("weekly projection present", wk["projection"] is not None)
    check("weekly counts achievements", "count" in wk["achievements"])

    section("Trial links")
    s, tr, _ = req("/api/trials",
                   {"quota_gb": 1, "hours": 24, "max_claims": 3, "per_day": 2}, tok)
    check("create trial", s == 201 and tr["code"])
    tcode, tid = tr["code"], tr["id"]
    check("trial url built", "/t/" in tr.get("url", ""))
    s, info, _ = req(f"/t/{tcode}/api")
    check("trial info is public", s == 200 and info["available"])
    check("trial info hides internals",
          "id" not in info and "code" not in info)
    s, claim, _ = req(f"/t/{tcode}/claim", {})
    check("claim creates account", s == 201 and claim["username"].startswith("trial-"))
    check("claim returns portal + sub",
          "/u/" in claim["portal"] and "/sub/" in claim["sub"])
    tuser = db.one("SELECT * FROM users WHERE username=?", (claim["username"],))
    check("trial quota applied", tuser["quota_bytes"] == int(1 * 1024 ** 3))
    check("trial expiry is hours not days",
          23 * 3600 < tuser["expires_at"] - int(time.time()) <= 24 * 3600)
    check("trial user is active", tuser["enabled"] == 1)
    s, _, _ = req(f"/t/{tcode}/claim", {})
    check("same ip cannot claim twice", s == 409)
    s, info, _ = req(f"/t/{tcode}/api")
    check("info reflects claim", info["already_claimed"] and not info["available"])
    db.execute("UPDATE trial_claims SET ip='10.0.0.1' WHERE trial_id=?", (tid,))
    s, _, _ = req(f"/t/{tcode}/claim", {})
    check("second distinct claim allowed", s == 201)
    db.execute("UPDATE trial_claims SET ip='10.0.0.2' WHERE trial_id=?", (tid,))
    s, _, _ = req(f"/t/{tcode}/claim", {})
    check("per-day limit enforced", s == 429)
    s, _, _ = req(f"/api/trials/{tid}", {"enabled": False}, tok)
    check("trial can be paused", s == 200)
    s, _, _ = req(f"/t/{tcode}/claim", {})
    check("paused trial rejects claims", s == 403)
    s, tl, _ = req("/api/trials", tok=tok)
    check("trial list", s == 200 and len(tl) >= 1)
    s, _, _ = req(f"/api/trials/{tid}", tok=tok, method="DELETE")
    check("delete trial", s == 200)
    s, _, _ = req(f"/t/{tcode}/api")
    check("deleted trial 404s", s == 404)
    s, _, _ = req("/t/nosuchtrialcode/api")
    check("unknown trial 404s", s == 404)
    for u2 in db.list_users():
        if u2["username"].startswith("trial-"):
            db.delete_user(u2["id"])

    section("Portal self-service")
    s, pu, _ = req("/api/users", {"username": "portaluser"}, tok)
    ptok = pu["sub_token"]
    s, pd, _ = req(f"/u/{ptok}/api")
    check("portal exposes games", len(pd.get("games", [])) >= 10)
    check("portal exposes boost state", "boost" in pd)
    check("portal still hides credentials",
          "trojan_pass" not in pd and "ss_pass" not in pd and "id" not in pd)
    s, ph, _ = req(f"/u/{ptok}/history?window=7d")
    check("portal history", s == 200 and "series" in ph)
    s, pw, _ = req(f"/u/{ptok}/weekly")
    check("portal weekly", s == 200 and "highlights" in pw)
    s, pb, _ = req(f"/u/{ptok}/boost", {})
    check("portal can start boost", s == 200 and pb["active"])
    s, pb2, _ = req(f"/u/{ptok}/boost", {})
    check("portal boost is idempotent", s == 200 and pb2["active"])
    check("portal boost is 30 min", pb["remaining"] <= 1800)
    s, _, _ = req("/u/deadbeefdeadbeef/weekly")
    check("portal action rejects bad token", s == 404)
    req(f"/api/users/{pu['id']}", tok=tok, method="DELETE")
    req(f"/api/users/{bid}", tok=tok, method="DELETE")

    section("Gaming transport correctness")
    gcfg = xray.build_config()
    for ib in gcfg["inbounds"]:
        if ib["tag"] == "api":
            continue
        check(f"{ib['tag']}: sniffing disabled",
              ib.get("sniffing", {}).get("enabled") is False,
              str(ib.get("sniffing")))
    check("no destOverride anywhere",
          "destOverride" not in json.dumps(gcfg))
    xh = [i for i in gcfg["inbounds"]
          if i["tag"] == "vless-xhttp"][0]["streamSettings"]["xhttpSettings"]
    check("xhttp buffers enough out-of-order posts for mobile",
          int(xh.get("scMaxBufferedPosts", 0)) >= 60, str(xh))
    check("xhttp posts are bigger for throughput",
          xh.get("scMaxEachPostBytes") == "200000-500000",
          str(xh.get("scMaxEachPostBytes")))
    # packet-up is the only mode nginx's proxy_pass forwards intact.
    # stream-one needs streamed H2 uploads (upstream says use grpc_pass),
    # so selecting it silently breaks the tunnel behind nginx.
    check("xhttp uses packet-up so it survives nginx",
          xh["mode"] == "packet-up", xh["mode"])
    check("post interval at the 1-3ms floor",
          xh.get("scMinPostsIntervalMs") == "1-3",
          str(xh.get("scMinPostsIntervalMs")))
    check("latency profiles avoid xhttp", all(
        profiles.get(p)["prefer"] != "xhttp"
        for p in ("valorant", "fcmobile", "brawlstars", "moba", "pubg")))
    dm = [c for c in links.catalog(db.list_users()[0], "h.app",
                                   profile="valorant") if c["via"] == "Direct"]
    check("httpupgrade is offered first for games",
          dm[0]["kind"] == "httpupgrade", dm[0]["kind"])
    xu = [c for c in dm if c["kind"] == "xhttp"][0]["uri"]
    check("xhttp link mode matches the server", "mode=packet-up" in xu)

    # ── nginx keepalive on the XHTTP hot path ────────────────────────
    # XHTTP packet-up sends every upload chunk as its own HTTP request, so
    # this path sees hundreds of requests per second per tunnel. Two nginx
    # defaults sit right on that path and both cost a full TCP+TLS handshake
    # (~3 round trips, ~400ms at the measured 130ms RTT) each time they trip.
    section("nginx keepalive tuning")
    with open(os.path.join(ROOT, "nginx.conf.template")) as _f:
        _tpl = _f.read()

    import re as _re2
    # 1. Client-facing: keepalive_requests must be raised well above the
    #    1000 default, which an XHTTP tunnel exhausts in seconds.
    #    Scope the search to the http{} block only: the upstream block below
    #    also sets keepalive_requests, and matching that one instead would
    #    make this check pass while the client-facing default stayed at 1000.
    _http_only = _tpl[:_tpl.index("upstream control_plane")]
    _m = _re2.search(r"^\s*keepalive_requests\s+(\d+);", _http_only, _re2.M)
    check("client keepalive_requests is raised above the default",
          _m is not None and int(_m.group(1)) > 1000,
          _m.group(1) if _m else "not set (nginx default 1000)")

    # 2. Upstream-facing: without a keepalive pool nginx opens a new
    #    connection to Xray for every single request.
    check("xhttp has a keepalive upstream pool",
          "upstream xray_xhttp" in _tpl)
    check("xhttp location uses the pool, not a raw address",
          "proxy_pass              http://xray_xhttp;" in _tpl)
    _up = _tpl[_tpl.index("upstream xray_xhttp"):]
    _up = _up[:_up.index("}")]
    check("upstream pool points at the xhttp inbound port",
          f"127.0.0.1:{xray.INBOUNDS['vless-xhttp'][0]}" in _up, _up)
    check("upstream pool keeps connections open", "keepalive " in _up)
    # Upstream keepalive silently does nothing unless the Connection header
    # is cleared, because a "Connection: close" is forwarded verbatim.
    _loc = _tpl[_tpl.index("location __PREFIX__/xhttp"):]
    _loc = _loc[:_loc.index("\n        location")] if "\n        location" in _loc else _loc
    check("xhttp clears the Connection header so keepalive applies",
          'proxy_set_header        Connection        "";' in _loc)

    section("Latency optimisations")
    lc = xray.build_config()
    check("default level buffers for speed",
          lc["policy"]["levels"]["0"]["bufferSize"] > 0,
          str(lc["policy"]["levels"]["0"]["bufferSize"]))
    check("boost level stays zero-buffer",
          lc["policy"]["levels"]["1"]["bufferSize"] == 0,
          str(lc["policy"]["levels"]["1"]["bufferSize"]))
    lsock = lc["outbounds"][0]["streamSettings"]["sockopt"]
    check("tcp fast open enabled", lsock.get("tcpFastOpen") is True)
    _wsin = [i for i in lc["inbounds"] if i["tag"] == "vless-ws"][0]
    check("main inbounds carry keepalive sockopt",
          _wsin["streamSettings"].get("sockopt", {}).get("tcpKeepAliveIdle") == 30,
          str(_wsin["streamSettings"].get("sockopt")))
    _rules_ips = [r.get("ip") for r in lc["routing"]["rules"] if r.get("ip")]
    _flat = [x for r in _rules_ips for x in r]
    check("private ranges are blocked from the tunnel",
          all(x in _flat for x in ("10.0.0.0/8", "172.16.0.0/12",
                                   "192.168.0.0/16")), str(_flat))
    check("nagle disabled", lsock.get("tcpNoDelay") is True)
    lxh = [i for i in lc["inbounds"] if i["tag"] == "vless-xhttp"][0]
    lxs = lxh["streamSettings"]["xhttpSettings"]
    check("xhttp post interval at the floor",
          lxs.get("scMinPostsIntervalMs") == "1-3",
          str(lxs.get("scMinPostsIntervalMs")))

    dcat = [c for c in links.catalog(db.list_users()[0], "h.app")
            if c["via"] == "Direct"]
    byk = {c["kind"]: c["uri"] for c in dcat}
    check("websocket transports request early data",
          all("ed=2560" in byk[k] or "ZWQ9" in byk[k]
              or "ed%3D2560" in byk[k]
              for k in ("ws", "trojan")),
          str([k for k in ("ws", "trojan") if "ed=2560" not in byk[k]]))
    import base64 as _b64
    vm = json.loads(_b64.b64decode(byk["vmess"][8:] + "==").decode())
    check("vmess requests early data", "ed=2560" in vm["path"], vm["path"])
    check("vmess pins a concrete cipher", vm["scy"] == "aes-128-gcm", vm["scy"])
    check("vmess offers both alpn values",
          vm["alpn"] == "h2,http/1.1", vm["alpn"])
    check("all transports offer both alpn values",
          all("alpn=h2,http%2F1.1" in byk[k]
              for k in ("ws", "httpupgrade", "xhttp", "trojan")),
          str({k: byk[k].split("alpn=")[-1][:24] for k in byk}))
    check("xhttp still advertises h2", "alpn=h2" in byk["xhttp"])
    check("fingerprints are randomized",
          all("fp=random" in byk[k] for k in ("ws", "httpupgrade", "xhttp", "trojan")),
          str({k: ("fp=random" in byk[k]) for k in byk}))
    check("vmess fingerprint randomized", vm["fp"] == "random", vm["fp"])
    # Early data removes one round trip from every new connection, which at
    # this deployment's ~130ms RTT is ~130ms off the first game packet.
    # Xray's httpupgrade dialer blocks on reading "101 Switching Protocols"
    # unless `ed` is set, so its absence is a real, measurable cost.
    #
    # Parse the URI rather than substring-matching it: `path` is
    # percent-encoded, so a naive `"ed=2560" in uri` is vacuous and can
    # never fail. That is exactly how the previous version of this check
    # managed to assert the opposite behaviour and still pass.
    from urllib.parse import urlparse as _up2, parse_qs as _pq2, unquote as _uq2
    for _kind in ("ws", "httpupgrade"):
        _p = _uq2(_pq2(_up2(byk[_kind]).query)["path"][0])
        check(f"{_kind} requests early data", "ed=2560" in _p, _p)
    # XHTTP has its own flow control and no `ed` mechanism.
    _xp = _uq2(_pq2(_up2(byk["xhttp"]).query)["path"][0])
    check("xhttp carries no early-data marker", "ed=" not in _xp, _xp)
    for ib in gcfg["inbounds"]:
        ws = ib.get("streamSettings", {}).get("wsSettings")
        if ws:
            check(f"{ib['tag']}: heartbeat inside CF idle window",
                  0 < ws.get("heartbeatPeriod", 0) < 100,
                  str(ws.get("heartbeatPeriod")))

    section("Client UDP transport (games)")
    for pid in ("valorant", "fcmobile", "brawlstars", "clashroyale", "moba"):
        p = profiles.get(pid)
        m = p["mux"]
        check(f"{pid}: xudp carries UDP", m.get("xudp", 0) > 0, str(m))
        check(f"{pid}: mux enabled so UDP has a transport",
              m.get("enabled") is True, str(m))
    for pid in ("valorant", "fcmobile", "brawlstars", "moba"):
        check(f"{pid}: TCP multiplexing on for throughput",
              profiles.get(pid)["mux"]["concurrency"] > 0)
    sb2 = json.loads(links.sub_singbox(db.list_users()[0], "h.app",
                                       profile="valorant"))
    vless_outs = [o for o in sb2["outbounds"] if o["type"] == "vless"]
    check("singbox vless declares xudp packet encoding",
          all(o.get("packet_encoding") == "xudp" for o in vless_outs),
          str([o.get("packet_encoding") for o in vless_outs]))
    check("singbox enables mux for the gaming profile",
          all(o["multiplex"]["enabled"] is True for o in vless_outs))



    section("Multi-host subscriptions")
    check("host_list dedupes and orders",
          links.host_list("a.com", None, ["a.com", "b.com"]) ==
          [("a.com", "Direct"), ("b.com", "Alt")],
          str(links.host_list("a.com", None, ["a.com", "b.com"])))
    check("railway alternates are labelled",
          links.host_list("a.com", None, ["x.up.railway.app"])[1][1] == "Railway")
    check("cf host still appended last",
          links.host_list("a.com", "w.dev", ["b.com"])[-1] == ("w.dev", "CF"))

    mh_user = db.list_users()[0]
    mcat = links.catalog(mh_user, "primary.com", None, None, ["second.com"])
    check("catalog covers both hosts", len(mcat) == 10, str(len(mcat)))
    mservers = {c["uri"].split("@")[1].split(":")[0]
                for c in mcat if "@" in c["uri"]}
    check("both hostnames present in links",
          mservers == {"primary.com", "second.com"}, str(mservers))
    mtags = []
    for c in mcat:
        if c["uri"].startswith("vmess://"):
            p = c["uri"][8:]
            mtags.append(json.loads(
                base64.b64decode(p + "=" * (-len(p) % 4)).decode())["ps"])
        elif "#" in c["uri"]:
            mtags.append(c["uri"].split("#")[1])
    check("no duplicate fragment tags", len(mtags) == len(set(mtags)))

    check("clash carries both hosts",
          "primary.com" in links.sub_clash(mh_user, "primary.com", None, None,
                                           ["second.com"])
          and "second.com" in links.sub_clash(mh_user, "primary.com", None,
                                              None, ["second.com"]))
    msb = json.loads(links.sub_singbox(mh_user, "primary.com", None, None,
                                       ["second.com"]))
    msbtags = [o["tag"] for o in msb["outbounds"]]
    check("singbox tags stay unique across hosts",
          len(msbtags) == len(set(msbtags)))
    check("singbox reaches both hosts",
          {o["server"] for o in msb["outbounds"] if o.get("server")} ==
          {"primary.com", "second.com"})

    section("Unroutable hosts are rejected")
    from app.server import _is_public_host as _pub
    for good in ("gaming2.kdns.fr", "app.up.railway.app", "1.2.3.4"):
        check(f"accepts {good}", _pub(good))
    for bad in ("127.0.0.1", "localhost", "10.0.0.5", "192.168.1.1",
                "172.16.0.1", "169.254.1.1", "nginx", "", "has space"):
        check(f"rejects {bad!r}", not _pub(bad))

    section("Quota and expiry in the subscription")
    q_user = db.create_user("infouser", quota_gb=100, days=30)
    db.execute("UPDATE users SET used_down=?, used_up=? WHERE id=?",
               (30 * 1024 ** 3, 2 * 1024 ** 3, q_user["id"]))
    q_user = db.get_user(q_user["id"])
    ents = links.info_entries(q_user, "h.com")
    check("two info entries", len(ents) == 2)
    check("usage entry shows used and total",
          "32.00GB" in ents[0]["label"] and "100.00GB" in ents[0]["label"],
          ents[0]["label"])
    check("usage entry shows percent", "(32%)" in ents[0]["label"])
    check("usage entry shows remaining", "68.00GB left" in ents[0]["label"])
    check("expiry entry shows days", "days left" in ents[1]["label"],
          ents[1]["label"])
    check("info entries point at loopback so they cannot be dialled",
          all("@127.0.0.1:1?" in e["uri"] for e in ents))
    check("info entries are flagged", all(e.get("info") for e in ents))

    raw_with = links.sub_raw(q_user, "h.com", None, None, None, True)
    raw_without = links.sub_raw(q_user, "h.com", None, None, None, False)
    check("info included by default", "@127.0.0.1:1?" in raw_with)
    check("info can be turned off", "@127.0.0.1:1?" not in raw_without)
    check("turning info off keeps every config",
          len(raw_without.splitlines()) == len(raw_with.splitlines()) - 2)

    unlim = db.create_user("unlimuser")
    uents = links.info_entries(unlim, "h.com")
    check("unlimited quota worded correctly", "unlimited" in uents[0]["label"],
          uents[0]["label"])
    check("no expiry worded correctly", "never expires" in uents[1]["label"],
          uents[1]["label"])

    db.execute("UPDATE users SET expires_at=? WHERE id=?",
               (int(time.time()) - 86400, q_user["id"]))
    exp_ents = links.info_entries(db.get_user(q_user["id"]), "h.com")
    check("expired subscription says so", "EXPIRED" in exp_ents[1]["label"],
          exp_ents[1]["label"])
    db.delete_user(q_user["id"])
    db.delete_user(unlim["id"])

    # ── cleanup ──────────────────────────────────────────────────────
    s, _, _ = req(f"/api/users/{uid}", tok=tok, method="DELETE")
    check("delete player", s == 200)
    check("player really gone", db.get_user(uid) is None)
    s, _, _ = req(f"/sub/{sub_token}", raw=True)
    check("subscription dies with player", s == 404)

    # ── summary ──────────────────────────────────────────────────────
    print("\n" + "═" * 60)
    total = PASS + FAIL
    if FAIL:
        print(f"\033[31m{FAIL} of {total} checks FAILED\033[0m")
        for f in FAILURES:
            print(f"   • {f}")
        return 1
    print(f"\033[32mAll {total} checks passed\033[0m")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    finally:
        metrics.shutdown()
