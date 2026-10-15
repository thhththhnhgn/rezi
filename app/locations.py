"""
ULTRA GAMING VPN — multi-country exit locations.

How it works
------------
One Tor instance per country runs inside the container, each pinned to exit
in that country:

    client ──► nginx /<prefix>/l/<code> ──► Xray inbound ──► SOCKS ──► Tor ──► exit

Tor's `ExitNodes {cc}` + `StrictNodes 1` is what forces the country. Xray
reaches each instance through a plain SOCKS outbound, and a routing rule
binds one inbound tag to one outbound tag.

Read this before enabling anything
----------------------------------
Tor relays traffic through three volunteer-run hops in arbitrary parts of
the world, so a location config costs 500-3000ms of latency versus the
~130ms of a direct config. It is useful for reaching things that are
region-locked or that block the datacentre, and it is useless for gaming.
The panel labels these configs accordingly and never offers one as the
default.

Design choices that differ from the reference implementation
------------------------------------------------------------
* Bootstrapping happens on a background thread. The reference blocks
  startup until every Tor instance has bootstrapped and verified, so a slow
  or unreachable Tor network takes the whole panel down with it. Here the
  panel serves normally and locations appear as they come up.
* Verification is one request, not two. Asking a combined endpoint for
  {ip, country} halves the round trips through a very slow circuit.
* Off by default, and every instance costs ~40MB RSS. Enabling ten on a
  small Railway container is roughly 400MB of Tor alone, which is why the
  count is capped and the default is empty.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import tempfile
import threading
import time

from . import db

TOR_BIN = os.environ.get("TOR_BIN", "/usr/bin/tor")
TOR_DIR = os.environ.get("TOR_DIR", "/tmp/tor")

# Port bases. Kept clear of the transport inbounds (7001-7005), the control
# plane (8888) and the Xray API (10085).
#
# Ports are allocated by index in the FULL sorted country list (stride 4),
# not by position in the enabled subset, so toggling one country on or off
# never shifts another country's ports. 190 countries -> socks up to ~9810,
# control up to ~11810, inbound up to ~13810: all clear.
SOCKS_BASE = 9050
CONTROL_BASE = 11050
INBOUND_BASE = 13050
PORT_STRIDE = 4

# Each Tor process is ~40MB RSS and needs its own circuit. Ten is the
# reference implementation's number; it is also enough to exhaust a small
# container, so treat it as a hard ceiling rather than a target. Raise it
# via MAX_LOCATIONS only if the container has the RAM to back it up.
MAX_LOCATIONS = int(os.environ.get("MAX_LOCATIONS", "10"))

# Countries that must never be used as an exit or as an intermediate relay:
# either hostile to this user or so heavily censored that routing through
# them is worse than not routing at all.
#
# These are also passed to Tor as ExcludeNodes/ExcludeExitNodes, which is
# why the list includes countries a user would never type: the entry and
# middle hops are chosen by Tor, not by us, and a circuit that transits a
# hostile network defeats the point of using one.
#
# The list is overridable through LOCATION_EXCLUDE (comma separated) for
# deployments that want a different policy. Excluded countries are hidden
# from the panel entirely: they can never be enabled, so showing them as
# "blocked" cards would only invite clicking them.
_DEFAULT_EXCLUDE = (
    "ir", "kp", "cn", "ru", "sy", "cu", "ve", "by",
    "uz", "kz", "tm", "kg", "tj", "az", "am",
)
_EXCLUDE_ENV = os.environ.get("LOCATION_EXCLUDE", "").strip()
EXCLUDE: tuple = tuple(
    "".join(ch for ch in c.strip().lower() if ch.isalpha())[:2]
    for c in _EXCLUDE_ENV.replace(";", ",").split(",")
) if _EXCLUDE_ENV else _DEFAULT_EXCLUDE


def excluded(code: str) -> bool:
    return code in EXCLUDE


# Every country Tor can exit through, with a human label. Codes are ISO
# 3166-1 alpha-2; anything in this table can be activated from the panel
# (unless EXCLUDE says otherwise). Entries Tor has never heard of are still
# listed — they simply fail verification and stay "failed" until removed.
COUNTRIES = {
    "ad": "Andorra", "ae": "United Arab Emirates", "af": "Afghanistan",
    "ag": "Antigua and Barbuda", "al": "Albania", "am": "Armenia",
    "ao": "Angola", "ar": "Argentina", "at": "Austria", "au": "Australia",
    "az": "Azerbaijan", "ba": "Bosnia and Herzegovina", "bb": "Barbados",
    "bd": "Bangladesh", "be": "Belgium", "bf": "Burkina Faso",
    "bg": "Bulgaria", "bh": "Bahrain", "bi": "Burundi", "bj": "Benin",
    "bn": "Brunei", "bo": "Bolivia", "br": "Brazil", "bs": "Bahamas",
    "bt": "Bhutan", "bw": "Botswana", "by": "Belarus", "bz": "Belize",
    "ca": "Canada", "cd": "Congo (DRC)", "cf": "Central African Republic",
    "cg": "Congo", "ch": "Switzerland", "ci": "Côte d'Ivoire",
    "cl": "Chile", "cm": "Cameroon", "cn": "China", "co": "Colombia",
    "cr": "Costa Rica", "cu": "Cuba", "cv": "Cape Verde", "cy": "Cyprus",
    "cz": "Czechia", "de": "Germany", "dj": "Djibouti", "dk": "Denmark",
    "dm": "Dominica", "do": "Dominican Republic", "dz": "Algeria",
    "ec": "Ecuador", "ee": "Estonia", "eg": "Egypt", "er": "Eritrea",
    "es": "Spain", "et": "Ethiopia", "fi": "Finland", "fj": "Fiji",
    "fm": "Micronesia", "fr": "France", "ga": "Gabon", "gb": "United Kingdom",
    "gd": "Grenada", "ge": "Georgia", "gh": "Ghana", "gm": "Gambia",
    "gn": "Guinea", "gq": "Equatorial Guinea", "gr": "Greece",
    "gt": "Guatemala", "gw": "Guinea-Bissau", "gy": "Guyana",
    "hk": "Hong Kong", "hn": "Honduras", "hr": "Croatia", "ht": "Haiti",
    "hu": "Hungary", "id": "Indonesia", "ie": "Ireland", "il": "Israel",
    "in": "India", "iq": "Iraq", "ir": "Iran", "is": "Iceland",
    "it": "Italy", "jm": "Jamaica", "jo": "Jordan", "jp": "Japan",
    "ke": "Kenya", "kg": "Kyrgyzstan", "kh": "Cambodia", "ki": "Kiribati",
    "km": "Comoros", "kn": "St Kitts and Nevis", "kp": "North Korea",
    "kr": "South Korea", "kw": "Kuwait", "kz": "Kazakhstan", "la": "Laos",
    "lb": "Lebanon", "lc": "St Lucia", "li": "Liechtenstein",
    "lk": "Sri Lanka", "lr": "Liberia", "ls": "Lesotho", "lt": "Lithuania",
    "lu": "Luxembourg", "lv": "Latvia", "ly": "Libya", "ma": "Morocco",
    "mc": "Monaco", "md": "Moldova", "me": "Montenegro", "mg": "Madagascar",
    "mh": "Marshall Islands", "mk": "North Macedonia", "ml": "Mali",
    "mm": "Myanmar", "mn": "Mongolia", "mo": "Macau", "mr": "Mauritania",
    "mt": "Malta", "mu": "Mauritius", "mv": "Maldives", "mw": "Malawi",
    "mx": "Mexico", "my": "Malaysia", "mz": "Mozambique", "na": "Namibia",
    "ne": "Niger", "ng": "Nigeria", "ni": "Nicaragua", "nl": "Netherlands",
    "no": "Norway", "np": "Nepal", "nr": "Nauru", "nz": "New Zealand",
    "om": "Oman", "pa": "Panama", "pe": "Peru", "pg": "Papua New Guinea",
    "ph": "Philippines", "pk": "Pakistan", "pl": "Poland", "ps": "Palestine",
    "pt": "Portugal", "pw": "Palau", "py": "Paraguay", "qa": "Qatar",
    "ro": "Romania", "rs": "Serbia", "ru": "Russia", "rw": "Rwanda",
    "sa": "Saudi Arabia", "sb": "Solomon Islands", "sc": "Seychelles",
    "sd": "Sudan", "se": "Sweden", "sg": "Singapore", "si": "Slovenia",
    "sk": "Slovakia", "sl": "Sierra Leone", "sm": "San Marino",
    "sn": "Senegal", "so": "Somalia", "sr": "Suriname", "ss": "South Sudan",
    "st": "São Tomé and Príncipe", "sv": "El Salvador", "sy": "Syria",
    "sz": "Eswatini", "td": "Chad", "tg": "Togo", "th": "Thailand",
    "tj": "Tajikistan", "tl": "Timor-Leste", "tm": "Turkmenistan",
    "tn": "Tunisia", "to": "Tonga", "tr": "Turkey", "tt": "Trinidad and Tobago",
    "tv": "Tuvalu", "tw": "Taiwan", "tz": "Tanzania", "ua": "Ukraine",
    "ug": "Uganda", "us": "United States", "uy": "Uruguay",
    "uz": "Uzbekistan", "va": "Vatican City", "vc": "St Vincent and the Grenadines",
    "ve": "Venezuela", "vn": "Vietnam", "vu": "Vanuatu", "ws": "Samoa",
    "ye": "Yemen", "za": "South Africa", "zm": "Zambia", "zw": "Zimbabwe",
}

# Backwards-compatible alias: code -> human label.
NAMES = COUNTRIES

# Persian names for the countries that can appear in the panel. The panel
# shows these when the UI language is فارسی and searches them too. Missing
# entries fall back to the English label.
NAMES_FA = {
    "ae": "امارات متحده عربی", "ar": "آرژانتین", "at": "اتریش",
    "au": "استرالیا", "az": "آذربایجان", "be": "بلژیک", "bg": "بلغارستان",
    "ca": "کانادا", "ch": "سوئیس", "cl": "شیلی", "cr": "کاستاریکا",
    "cy": "قبرس", "cz": "جمهوری چک", "de": "آلمان", "dk": "دانمارک",
    "ee": "استونی", "es": "اسپانیا", "fi": "فنلاند", "fr": "فرانسه",
    "gb": "بریتانیا", "gr": "یونان", "hk": "هنگ‌کنگ", "hr": "کرواسی",
    "hu": "مجارستان", "id": "اندونزی", "il": "اسرائیل", "is": "ایسلند",
    "it": "ایتالیا", "jp": "ژاپن", "kr": "کره جنوبی", "lt": "لیتوانی",
    "lu": "لوکزامبورگ", "md": "مولداوی", "mx": "مکزیک", "my": "مالزی",
    "nl": "هلند", "no": "نروژ", "nz": "نیوزیلند", "pe": "پرو",
    "pl": "لهستان", "pt": "پرتغال", "ro": "رومانی", "rs": "صربستان",
    "se": "سوئد", "sg": "سنگاپور", "tr": "ترکیه", "tw": "تایوان",
    "ua": "اوکراین", "us": "ایالات متحده", "vn": "ویتنام",
    "za": "آفریقای جنوبی",
}

# Every code, sorted. Port allocation is indexed on THIS list (not on
# the enabled subset), so toggling countries on and off never shifts another
# country's ports mid-run.
_ALL_SORTED = sorted(COUNTRIES)

# ── countries that actually run Tor exit relays ─────────────────────────
# The panel only lists countries where Tor really has exits — a country
# with zero relays can never connect, so listing it is noise (Palestine,
# for example, has none).
#
# This dict is the BUNDLED snapshot: code -> approximate number of running
# exit relays, taken from onionoo.torproject.org on 2026-08-02 (all 7
# pages of `details?flag=exit&running=true&fields=country`). Counts are
# rounded; only their order of magnitude matters (they drive the
# "scarce" label for countries below ~10 relays).
#
# At boot the panel tries to refresh this from onionoo and stores the live
# counts in the DB (see refresh_exit_counts / ensure_refresh); the bundled
# map is only the offline fallback. Counts are approximate on purpose —
# the runtime verification is what actually decides whether a country
# comes up, never this number.
EXIT_COUNTRIES: dict[str, int] = {
    "us": 380, "nl": 330, "de": 280, "se": 240, "at": 90, "lu": 70,
    "fr": 55, "ro": 50, "ch": 30, "ua": 25, "sg": 20, "no": 18,
    "it": 15, "fi": 12, "is": 12, "dk": 12, "za": 12, "es": 12,
    "ca": 10, "cz": 10, "hu": 10, "gb": 10, "pl": 8, "bg": 8,
    "hr": 7, "jp": 5, "id": 4, "my": 4, "hk": 4, "md": 4,
    "tw": 3, "vn": 3, "ee": 3, "au": 3, "tr": 3, "cl": 2,
    "cr": 2, "nz": 2, "rs": 2, "pe": 2, "cy": 2, "il": 1,
    "kr": 1, "lt": 1, "mx": 1, "pt": 1, "gr": 1, "az": 1,
    "ae": 1, "ar": 1, "be": 1,
}

_counts_cache: tuple[float, dict] | None = None
_REFRESH_TTL = 86400          # re-fetch onionoo at most once a day


def _exit_counts() -> dict[str, int]:
    """Live exit-relay counts from the DB, falling back to the bundled map.

    Cached briefly because the locations page calls it once per card.
    """
    global _counts_cache
    now = time.time()
    if _counts_cache and now - _counts_cache[0] < 120:
        return _counts_cache[1]
    val = db.get_setting("loc_exit_counts", None)
    out: dict[str, int] = {}
    if isinstance(val, dict):
        for k, v in val.items():
            k = str(k).strip().lower()
            if len(k) == 2 and k in COUNTRIES:
                try:
                    out[k] = max(1, int(v))
                except (TypeError, ValueError):
                    pass
    if not out:
        out = dict(EXIT_COUNTRIES)
    _counts_cache = (now, out)
    return out


def refresh_exit_counts() -> dict[str, int] | None:
    """Fetch the live exit-relay country counts from onionoo and store them.

    Returns the new counts, or None when the fetch fails (offline, timeout,
    garbage response) — callers keep whatever they had before.
    """
    try:
        import json as _json
        import urllib.request as _ur
        url = ("https://onionoo.torproject.org/details"
               "?flag=exit&running=true&fields=country")
        with _ur.urlopen(url, timeout=15) as r:
            data = _json.loads(r.read().decode("utf-8"))
        cnt: dict[str, int] = {}
        for rel in data.get("relays", []) or []:
            c = str(rel.get("country") or "").strip().lower()
            if len(c) == 2 and c in COUNTRIES:
                cnt[c] = cnt.get(c, 0) + 1
        if not cnt:
            return None
        cnt = {k: v for k, v in cnt.items() if v >= 1}
        db.set_setting("loc_exit_counts", cnt)
        db.set_setting("loc_exits_updated", int(time.time()))
        global _counts_cache
        _counts_cache = (time.time(), cnt)
        return cnt
    except Exception:
        return None


def ensure_refresh() -> None:
    """Kick off a background onionoo refresh when the cached data is stale.

    Runs once per boot at most (plus once a day on long-lived containers).
    Never blocks: the fetch happens on a daemon thread. Disable entirely
    with ONIONOO_REFRESH=0.
    """
    if os.environ.get("ONIONOO_REFRESH", "1").strip().lower() in (
            "0", "false", "no", "off"):
        return
    db.init()
    try:
        updated = db.get_setting("loc_exits_updated", None)
    except Exception:
        updated = None
    if updated and time.time() - int(updated or 0) < _REFRESH_TTL:
        return
    threading.Thread(target=_refresh_worker, name="onionoo-refresh",
                     daemon=True).start()


def _refresh_worker() -> None:
    try:
        cnt = refresh_exit_counts()
        if cnt:
            db.log_event(
                f"Exit-relay data refreshed: {len(cnt)} countries",
                kind="location")
    except Exception:
        pass


def relay_data() -> dict:
    """Small payload describing where the exit-relay list came from."""
    counts = _exit_counts()
    updated = db.get_setting("loc_exits_updated", None)
    live = bool(updated)
    return {
        "source": "live" if live else "bundled",
        "updated": int(updated) if live else None,
        "countries": len([c for c in counts
                          if c in COUNTRIES and c not in EXCLUDE]),
    }


def is_scarce(code: str) -> bool:
    """True for countries with very few exits (<10), so the panel can mark
    them as likely-to-fail. Falls back to the curated FRAGILE set when no
    live counts exist yet."""
    n = _exit_counts().get(code)
    if n is not None:
        return n < 10
    return code in FRAGILE

FLAGS = {
    "at": "🇦🇹", "be": "🇧🇪", "bg": "🇧🇬", "ca": "🇨🇦", "ch": "🇨🇭",
    "cz": "🇨🇿", "de": "🇩🇪", "dk": "🇩🇰", "ee": "🇪🇪", "es": "🇪🇸",
    "fi": "🇫🇮", "fr": "🇫🇷", "gb": "🇬🇧", "hu": "🇭🇺", "ie": "🇮🇪",
    "is": "🇮🇸", "it": "🇮🇹", "jp": "🇯🇵", "lt": "🇱🇹", "lu": "🇱🇺",
    "lv": "🇱🇻", "md": "🇲🇩", "nl": "🇳🇱", "no": "🇳🇴", "pl": "🇵🇱",
    "pt": "🇵🇹", "ro": "🇷🇴", "se": "🇸🇪", "sg": "🇸🇬", "sk": "🇸🇰",
    "tr": "🇹🇷", "ua": "🇺🇦", "us": "🇺🇸",
}


def _flag_emoji(code: str) -> str:
    """Emoji flag for any ISO code without keeping a 190-entry table."""
    try:
        return "".join(
            chr(0x1F1E6 + ord(ch) - ord("A")) for ch in code.upper()
        )
    except Exception:
        return "🌍"

# Endpoints that return the exit IP *and* its country in a single response.
# The reference implementation asks one service for the IP and then a second
# for the country, which is two full round trips through a Tor circuit that
# may already be taking seconds. These cost one.
#
# Ordered most-reliable first; the first one that answers wins. Extra
# entries are pure redundancy: every probe runs through a fresh Tor circuit
# that may take seconds, so a service being slow or down used to cost a
# whole verification attempt.
PROBES = (
    ("https://ipinfo.io/json", "ip", "country"),
    ("http://ip-api.com/json/", "query", "countryCode"),
    ("https://ipwho.is/", "ip", "country_code"),
    ("https://api.ip.sb/geoip", "ip", "country_code"),
    ("https://ipapi.co/json/", "ip", "country_code"),
    ("https://freeipapi.com/api/json", "ipAddress", "countryCode"),
)

# Default set used when LOCATIONS is "all" or "max".
#
# Ordered by how many *running exit relays* each country actually has,
# measured from onionoo (flag:exit running:true) rather than picked by
# reputation. Exit count decides whether a circuit can be built at all and
# how long verification takes, and the spread is enormous:
#
#     us 959   nl 607   de 414   se 341   at 122
#     lu  90   ro  70   fr  62   ch  25   tr   3
#
# Turkey replaces Finland (11 exits) by request. It is by far the most
# fragile entry in this list — the whole country has three exit relays:
#
#     salsedo 23 MB/s · faboulouswatermelon 7 MB/s · fumo 11 MB/s
#
# With StrictNodes 1 those three are the *only* nodes Tor may exit
# through, so if they are busy or down the circuit cannot be built and the
# location is dropped after verification fails. It is included anyway
# because it is geographically closest, and being dropped is a safe
# outcome: the config is simply never published. See FRAGILE below for how
# that failure is made visible rather than silent.
#
# Countries further down (gb 9, pl 7) are left out for the same reason
# with none of the proximity benefit.
TOP_LOCATIONS = ("nl", "de", "us", "se", "at", "lu", "ro", "fr", "ch", "tr")

# Countries known to have so few exit relays that failure is likely rather
# than exceptional. These get a longer verification budget — a scarce exit
# is often merely busy, and giving up after the standard number of tries
# would discard a country that would have worked on the next attempt.
# The panel also labels them so a FAILED card is understood as expected
# rather than as a bug.
FRAGILE = {"tr", "gb", "pl", "fi", "is", "lv", "ee", "sk", "hu", "bg", "md"}

# Patience settings.
#
# These are generous on purpose. A location that eventually verifies is
# worth far more than one abandoned early, and the cost of waiting is
# nothing: bootstrapping runs on a background thread, so the panel is
# already serving while this happens. The only thing a short timeout buys
# is an earlier "failed" card.
#
# Building a circuit through a country with few exits routinely takes
# several minutes, and every attempt that gives up too soon throws away a
# circuit that may have been one retry from working.
BOOTSTRAP_TIMEOUT = int(os.environ.get("TOR_BOOTSTRAP_TIMEOUT", "900"))
VERIFY_ATTEMPTS = int(os.environ.get("TOR_VERIFY_ATTEMPTS", "30"))
# Pause between verification attempts. Each SIGNAL NEWNYM needs a moment
# to actually produce a new circuit; retrying faster just re-probes the
# same one.
VERIFY_WAIT = int(os.environ.get("TOR_VERIFY_WAIT", "8"))
ROTATE_SECONDS = int(os.environ.get("TOR_ROTATE_SECONDS", "600"))

# A location that failed is retried from scratch rather than left dead.
# Exit availability changes constantly: a country with three relays can be
# unreachable for ten minutes and fine afterwards, and without this the
# only way to recover was a redeploy.
RETRY_FAILED_AFTER = int(os.environ.get("TOR_RETRY_FAILED_AFTER", "1800"))

_procs: dict[str, subprocess.Popen] = {}
_state: dict[str, dict] = {}
_lock = threading.RLock()
_stop = threading.Event()
_rotator_started = False


# ── configuration ────────────────────────────────────────────────────────

def _clean(code: str) -> str:
    return "".join(c for c in str(code).strip().lower() if c.isalpha())[:2]


def known_codes() -> list[str]:
    """Every country the panel may list, sorted.

    That means countries with running Tor exit relays (live data, or the
    bundled snapshot as fallback), MINUS excluded ones. Anything already
    enabled is always included too, so an active location can never
    disappear from the panel just because the last refresh had no relay
    for it.
    """
    db.init()
    codes = set(_exit_counts())
    codes |= set(configured())
    return sorted(c for c in codes if c in COUNTRIES and c not in EXCLUDE)


def _seed_from_env() -> list[str]:
    """First-boot migration: the enabled list starts EMPTY.

    The panel is the only place countries get activated — LOCATIONS is no
    longer auto-seeded, so every country starts disabled and the admin
    picks which ones to bring up. The env var is kept only as a
    compatibility no-op so existing deployments don't break.
    """
    db.set_setting("locations_enabled", [])
    return []


def _set_enabled(codes: list[str]) -> None:
    """Persist the enabled set. Invalid/excluded codes are dropped."""
    clean: list[str] = []
    for c in codes:
        c = _clean(c)
        if (len(c) == 2 and c in COUNTRIES and c not in EXCLUDE
                and c not in clean):
            clean.append(c)
    db.set_setting("locations_enabled", clean)


def configured() -> list[str]:
    """
    Country codes currently enabled (the ones with a Tor instance running
    or coming up).

    Source of truth is the `locations_enabled` DB setting, seeded from the
    LOCATIONS env var on first boot so existing deployments keep working
    unchanged. Invalid, excluded and duplicate entries are dropped rather
    than rejected, so one bad value cannot stop the rest from coming up.
    """
    # start.sh calls this before the control plane has booted, so the
    # schema may not exist yet — creating it is idempotent and safe.
    db.init()
    val = db.get_setting("locations_enabled", None)
    if val is None:
        val = _seed_from_env()
    out: list[str] = []
    for c in (val or []):
        c = _clean(c)
        if (len(c) == 2 and c in COUNTRIES and c not in EXCLUDE
                and c not in out):
            out.append(c)
    return out


def enabled() -> bool:
    return bool(configured()) and available()


def available() -> bool:
    return os.path.exists(TOR_BIN) or bool(shutil.which("tor"))


def ports(code: str) -> tuple[int, int, int]:
    """(socks, control, xray inbound) for a code.

    Indexed on the FULL sorted country list, so a code always gets the same
    ports no matter which other countries are enabled — toggling one can
    never shift another's ports, and a restart never changes them.
    """
    idx = _ALL_SORTED.index(code)
    base = idx * PORT_STRIDE
    return (SOCKS_BASE + base, CONTROL_BASE + base, INBOUND_BASE + base)


def label(code: str) -> str:
    return NAMES.get(code, code.upper())


def label_fa(code: str) -> str:
    """Persian name for a country; falls back to the English label."""
    return NAMES_FA.get(code) or label(code)


def flag(code: str) -> str:
    return FLAGS.get(code) or _flag_emoji(code)


def inbound_tag(code: str) -> str:
    return f"loc-{code}"


def path_for(code: str) -> str:
    from . import paths
    return f"{paths.PREFIX}/l/{code}"


# ── state ────────────────────────────────────────────────────────────────

def _pins() -> dict[str, str]:
    """code -> pinned exit IP, from the settings table (one query)."""
    out: dict[str, str] = {}
    try:
        for r in db.query(
                "SELECT key, value FROM settings WHERE key LIKE 'loc_pin:%'"):
            code = r["key"][len("loc_pin:"):]
            v = r["value"]
            try:
                ip = json.loads(v)
            except (ValueError, TypeError):
                ip = v
            if isinstance(ip, str) and ip.strip():
                out[code] = ip.strip()
    except Exception:
        pass
    return out


def snapshot() -> list[dict]:
    """
    Current status of every known (non-excluded) country, sorted by code.

    Disabled countries appear too, with state "idle", so the panel renders
    the full list and lets the admin flip each one on. Enabled countries
    sort first so the interesting cards are at the top of the page.
    """
    enabled_set = set(configured())
    pins = _pins()
    counts = _exit_counts()
    with _lock:
        out = []
        for c in known_codes():
            row = dict(_state.get(c) or {
                "code": c, "label": label(c), "flag": flag(c),
                "verified": False, "state": "idle", "exit_ip": None,
            })
            row["label_fa"] = label_fa(c)
            row["enabled"] = c in enabled_set
            row["pinned"] = pins.get(c, "")
            # How many running exit relays this country has right now —
            # honest context for "will this even come up?".
            row["relays"] = counts.get(c, 0)
            # Let the panel distinguish "this failed because the country
            # barely has exits" from "this failed unexpectedly".
            row["fragile"] = is_scarce(c)
            out.append(row)
        out.sort(key=lambda r: (not r["enabled"], r["code"]))
        return out


def one_snapshot(code: str) -> dict:
    """Snapshot entry for a single code (for API responses)."""
    for row in snapshot():
        if row["code"] == code:
            return row
    return {"code": code, "label": label(code), "label_fa": label_fa(code),
            "flag": flag(code), "verified": False, "state": "idle",
            "exit_ip": None, "enabled": False, "pinned": "",
            "fragile": code in FRAGILE}


def verified_codes() -> list[str]:
    with _lock:
        return [c for c in configured()
                if (_state.get(c) or {}).get("verified")]


def _set(code: str, **kw) -> None:
    with _lock:
        cur = _state.setdefault(code, {
            "code": code, "label": label(code), "flag": flag(code),
            "verified": False, "state": "pending", "exit_ip": None,
        })
        cur.update(kw)
        cur["updated_at"] = int(time.time())


# ── tor process management ───────────────────────────────────────────────

def _pinned(code: str) -> str:
    """The pinned exit IP for a code, or '' when not pinned."""
    v = db.get_setting(f"loc_pin:{code}", "")
    return v.strip() if isinstance(v, str) else ""


def _torrc(code: str, socks: int, control: int) -> str:
    data = os.path.join(TOR_DIR, code)
    os.makedirs(data, exist_ok=True)
    os.chmod(data, 0o700)

    exclude = ",".join("{%s}" % c for c in EXCLUDE)
    # A pinned exit replaces the country set entirely: with StrictNodes 1,
    # `ExitNodes 1.2.3.4` forces EVERY circuit through that one relay.
    # That is the point of pinning (a stable IP for a region-locked
    # service), and also its risk — if the relay goes down the location
    # cannot build circuits until unpinned. The panel says exactly that.
    pinned = _pinned(code)
    exit_nodes = pinned if pinned else "{%s}" % code
    body = f"""\
SocksPort 127.0.0.1:{socks}
ControlPort 127.0.0.1:{control}
CookieAuthentication 1
DataDirectory {data}
ExitNodes {exit_nodes}
StrictNodes 1
ExcludeNodes {exclude}
ExcludeExitNodes {exclude}
Log notice file {data}/notice.log
# A client-only relay: never serve as an exit or accept inbound circuits.
ClientOnly 1
# Fewer, longer-lived circuits. Rebuilding is expensive on a slow path and
# every rebuild risks landing on an exit in the wrong country.
MaxCircuitDirtiness 600
NewCircuitPeriod 120
# Skip the descriptor churn for relays we will never use as an exit.
LearnCircuitBuildTimeout 1
# Padding cells exist to defeat traffic analysis between the client and its
# guard. This client sits in a datacentre and carries VPN streams, so the
# defense buys nothing here while its scheduled wake-ups add jitter to
# circuits that are already the slowest path we offer.
ConnectionPadding 0
# ── latency / fail-fast ──────────────────────────────────────────────
# Railway has no IPv6 egress; asking for IPv6 only adds fallback delays
# when a relay advertises an AAAA record first.
ClientUseIPv6 0
# Give up on a dead SOCKS target quickly so a stalled circuit is retried
# instead of hanging the tunnel. (CircuitBuildTimeout is advisory on
# modern Tor — tor adapts its own timeout — but harmless to cap.)
SocksTimeout 30
CircuitBuildTimeout 30
"""
    rc = os.path.join(data, "torrc")
    # Atomic write: tor reads this file at startup, and a torn write from a
    # concurrent restart would make the instance fail to boot.
    fd, tmp = tempfile.mkstemp(dir=data, suffix=".torrc")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(body)
        os.replace(tmp, rc)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return rc


def _spawn(code: str) -> bool:
    socks, control, _ = ports(code)
    try:
        rc = _torrc(code, socks, control)
    except OSError as e:
        _set(code, state="error", reason=f"cannot write torrc: {e}")
        return False

    try:
        p = subprocess.Popen(
            [TOR_BIN, "-f", rc],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        _set(code, state="error", reason=f"cannot start tor: {e}")
        return False

    with _lock:
        _procs[code] = p
    _set(code, state="starting")
    return True


def _bootstrapped(code: str) -> bool:
    log = os.path.join(TOR_DIR, code, "notice.log")
    try:
        with open(log, errors="ignore") as f:
            return "Bootstrapped 100%" in f.read()
    except OSError:
        return False


def _alive(code: str) -> bool:
    with _lock:
        p = _procs.get(code)
    return bool(p and p.poll() is None)


# ── verification ─────────────────────────────────────────────────────────

def _probe(socks: int, timeout: int = 25) -> tuple[str, str] | None:
    """
    Ask, through the SOCKS proxy, what our exit IP and country are.

    curl is used because the standard library has no SOCKS support and the
    image already ships curl. Returns (ip, country) or None.
    """
    for url, ip_key, cc_key in PROBES:
        try:
            r = subprocess.run(
                ["curl", "-sS", "--max-time", str(timeout),
                 "--socks5-hostname", f"127.0.0.1:{socks}", url],
                capture_output=True, text=True, timeout=timeout + 5,
            )
            if r.returncode != 0 or not r.stdout.strip():
                continue
            data = json.loads(r.stdout)
            ip = str(data.get(ip_key) or "").strip()
            cc = _clean(data.get(cc_key) or "")
            if ip and len(cc) == 2:
                return ip, cc
        except Exception:
            continue
    return None


def _new_circuit(code: str) -> None:
    """Ask Tor for a fresh circuit over the control port."""
    _, control, _ = ports(code)
    cookie = os.path.join(TOR_DIR, code, "control_auth_cookie")
    try:
        with open(cookie, "rb") as f:
            hexcookie = f.read().hex()
    except OSError:
        return
    try:
        import socket
        with socket.create_connection(("127.0.0.1", control), timeout=8) as s:
            s.sendall(f"AUTHENTICATE {hexcookie}\r\n".encode())
            s.recv(256)
            s.sendall(b"SIGNAL NEWNYM\r\n")
            s.recv(256)
            s.sendall(b"QUIT\r\n")
    except Exception:
        pass


def _record_exit(code: str, ip: str) -> None:
    """Fold one exit sighting into the per-country history table."""
    if not ip:
        return
    now = int(time.time())
    try:
        with _lock:
            cur = (_state.get(code) or {}).get("exit_ip")
            if cur and cur != ip:
                # The exit rotated: close the previous row's window so its
                # duration is not inflated by the gap.
                db.execute(
                    "UPDATE loc_exits SET last_seen=? WHERE code=? AND ip=?",
                    (now, code, cur))
            db.execute(
                "INSERT INTO loc_exits(code,ip,first_seen,last_seen,count) "
                "VALUES(?,?,?,?,1) "
                "ON CONFLICT(code,ip) DO UPDATE SET "
                "last_seen=excluded.last_seen, count=count+1",
                (code, ip, now, now))
    except Exception:
        pass


def exit_history(code: str, limit: int = 5) -> list[dict]:
    """
    The most stable exit IPs seen for a country, best first.

    Ranked by total observed duration (last_seen - first_seen), with the
    share of the tracked window as a percentage. Tor rotates exits on its
    own, so this is a record of what actually served — the ones that
    survived longest are the ones worth pinning.
    """
    rows = db.query(
        "SELECT * FROM loc_exits WHERE code=? "
        "ORDER BY (last_seen-first_seen) DESC, count DESC LIMIT ?",
        (code, int(limit)))
    tot = db.one(
        "SELECT COALESCE(SUM(last_seen-first_seen),0) t FROM loc_exits "
        "WHERE code=?", (code,))
    total = int(tot["t"]) if tot else 0
    out = []
    for r in rows:
        dur = max(0, int(r["last_seen"]) - int(r["first_seen"]))
        out.append({
            "ip": r["ip"],
            "first_seen": r["first_seen"],
            "last_seen": r["last_seen"],
            "duration": dur,
            "count": int(r["count"]),
            "pct": round(dur / total * 100, 1) if total > 0 else 0.0,
        })
    return out


def _verify(code: str) -> bool:
    """
    Confirm the exit really is in the requested country.

    StrictNodes should make this redundant, but an exit's advertised country
    and its actual geolocation disagree often enough that serving an
    unverified config means handing out one that silently exits somewhere
    else. A config that lies about its country is worse than no config.
    """
    socks, _, _ = ports(code)
    # A country with only a handful of exits usually fails because those
    # few nodes are momentarily busy, not because none exists. Retrying
    # longer converts most of those into a working location, and costs
    # nothing for countries that succeed on the first try.
    budget = VERIFY_ATTEMPTS * 2 if is_scarce(code) else VERIFY_ATTEMPTS
    for attempt in range(1, budget + 1):
        if _stop.is_set():
            return False
        got = _probe(socks)
        if got:
            ip, cc = got
            if cc == code:
                _set(code, verified=True, state="ready", exit_ip=ip,
                     reason=None)
                _record_exit(code, ip)
                return True
            _set(code, state="verifying", exit_ip=ip,
                 reason=f"exit in {cc}, wanted {code} (try {attempt}/{budget})")
        else:
            _set(code, state="verifying",
                 reason=f"no exit IP yet (try {attempt}/{budget})")
        _new_circuit(code)
        _stop.wait(VERIFY_WAIT)
    # Say *why* it failed. "no exit found" on a country with three relays
    # is expected behaviour, and a card that explains that is far more
    # useful than one that looks like a bug in the panel.
    _set(code, verified=False, state="failed",
         reason=("this country has very few Tor exits — none were reachable"
                 if code in FRAGILE else "no exit found in this country"))
    return False


def _bring_up(code: str) -> None:
    if not _spawn(code):
        return

    waited = 0
    while waited < BOOTSTRAP_TIMEOUT and not _stop.is_set():
        if _bootstrapped(code):
            break
        if not _alive(code):
            _set(code, state="restarting")
            if not _spawn(code):
                return
        _stop.wait(3)
        waited += 3
    else:
        _set(code, verified=False, state="failed", reason="bootstrap timeout")
        return

    if _stop.is_set():
        return
    _set(code, state="verifying")
    ok = _verify(code)
    db.log_event(
        f"Location {code}: {'ready' if ok else 'unavailable'}",
        kind="location", level="info" if ok else "warn",
    )
    if ok:
        _reload_xray()


def _reload_xray() -> None:
    """
    Rebuild the Xray config so the new location becomes routable.

    Imported lazily: xray imports db, and importing it at module scope would
    make locations <-> xray a cycle.
    """
    try:
        from . import xray
        xray.reload()
    except Exception as e:      # never let a reload failure kill the thread
        db.log_event(f"Location reload failed: {e}",
                     kind="location", level="error")


def _kill(code: str) -> None:
    """Terminate a code's Tor process and drop it from the registry."""
    with _lock:
        p = _procs.pop(code, None)
    if p and p.poll() is None:
        try:
            p.send_signal(signal.SIGTERM)
            p.wait(timeout=10)
        except Exception:
            try:
                p.kill()
            except Exception:
                pass


def _is_public_ipv4(ip: str) -> bool:
    parts = str(ip).strip().split(".")
    if len(parts) != 4 or not all(p.isdigit() for p in parts):
        return False
    a, b, c, d = (int(p) for p in parts)
    if any(x > 255 for x in (a, b, c, d)):
        return False
    if a in (0, 10, 127) or (a == 169 and b == 254):
        return False
    if a == 172 and 16 <= b <= 31:
        return False
    if a == 192 and b == 168:
        return False
    return True


def start_code(code: str) -> dict:
    """Panel action: enable one country and begin bringing it up."""
    if code not in COUNTRIES or excluded(code):
        return {"ok": False, "error": "unknown or excluded country"}
    enabled_list = configured()
    if code not in _exit_counts() and code not in enabled_list:
        return {"ok": False,
                "error": "this country has no Tor exit relays right now"}
    if code not in enabled_list:
        if len(enabled_list) >= MAX_LOCATIONS:
            return {
                "ok": False,
                "error": (f"at most {MAX_LOCATIONS} locations can run at "
                          f"once (~40MB each); stop one first or raise "
                          f"MAX_LOCATIONS"),
            }
        _set_enabled(enabled_list + [code])
    # Already enabled but dead/failed: give it an immediate retry instead
    # of waiting for the rotation loop to notice.
    st = (_state.get(code) or {}).get("state")
    if st in ("failed", "error"):
        _set(code, state="restarting", reason="manual retry")
        threading.Thread(target=_bring_up, args=(code,),
                         name=f"tor-{code}-retry", daemon=True).start()
    elif st not in ("pending", "starting", "verifying", "ready",
                    "restarting"):
        _set(code, state="pending")
        threading.Thread(target=_bring_up, args=(code,),
                         name=f"tor-{code}", daemon=True).start()
    _ensure_rotator()
    db.log_event(f"Location {code}: enabled from panel", kind="location")
    return {"ok": True, "location": one_snapshot(code)}


def stop_code(code: str) -> dict:
    """Panel action: disable one country, kill its Tor, drop its configs."""
    if code not in configured():
        return {"ok": False, "error": "location is not enabled"}
    _set_enabled([c for c in configured() if c != code])
    _kill(code)
    was_verified = bool((_state.get(code) or {}).get("verified"))
    _set(code, verified=False, state="idle", exit_ip=None, reason=None)
    db.log_event(f"Location {code}: disabled from panel", kind="location")
    if was_verified:
        _reload_xray()   # drop its inbound + outbound from the live config
    return {"ok": True, "location": one_snapshot(code)}


def pin_exit(code: str, ip: str) -> dict:
    """Pin a specific exit IP: every circuit for this country exits there.

    Possible because Tor's ExitNodes accepts a bare IP; with StrictNodes 1
    the relay is forced. The risk is availability — one relay can go down —
    so the panel warns before offering it, and unpin_exit restores the
    country-wide set instantly.
    """
    if code not in COUNTRIES or excluded(code):
        return {"ok": False, "error": "unknown or excluded country"}
    ip = str(ip or "").strip()
    if not _is_public_ipv4(ip):
        return {"ok": False, "error": "not a public IPv4 address"}
    db.set_setting(f"loc_pin:{code}", ip)
    db.log_event(f"Location {code}: exit pinned to {ip}", kind="location",
                 level="warn")
    if code in configured():
        _restart_tor(code)
    return {"ok": True, "location": one_snapshot(code)}


def unpin_exit(code: str) -> dict:
    """Remove a pinned exit; the country set takes over again."""
    if code not in COUNTRIES or excluded(code):
        return {"ok": False, "error": "unknown or excluded country"}
    db.set_setting(f"loc_pin:{code}", "")
    db.log_event(f"Location {code}: exit unpinned", kind="location")
    if code in configured():
        _restart_tor(code)
    return {"ok": True, "location": one_snapshot(code)}


def _restart_tor(code: str) -> None:
    """Rebuild the torrc (pin changed) and bring the instance up again."""
    if not available():
        return   # nothing is running; the next start reads the new pin
    _kill(code)
    _set(code, state="restarting", reason="applying exit pin change")
    threading.Thread(target=_bring_up, args=(code,),
                     name=f"tor-{code}-restart", daemon=True).start()


def _retry_failed() -> None:
    """
    Give up locations a second chance.

    Exit availability is not static: a country with a handful of relays can
    be unreachable for a while and perfectly usable later. Without this a
    location that lost the race at boot stayed dead until the next deploy,
    which is the wrong outcome for exactly the countries that need the most
    patience.
    """
    for code in configured():
        if _stop.is_set():
            return
        with _lock:
            st = dict(_state.get(code) or {})
        if st.get("verified") or st.get("state") not in ("failed", "error"):
            continue
        if time.time() - int(st.get("updated_at") or 0) < RETRY_FAILED_AFTER:
            continue

        db.log_event(f"Location {code}: retrying", kind="location")
        _set(code, state="restarting", reason="retrying")
        # The old process may be alive but wedged on a dead circuit, so
        # replace it rather than reusing it.
        with _lock:
            p = _procs.pop(code, None)
        if p and p.poll() is None:
            try:
                p.send_signal(signal.SIGTERM)
                p.wait(timeout=10)
            except Exception:
                try:
                    p.kill()
                except Exception:
                    pass
        threading.Thread(target=_bring_up, args=(code,),
                         name=f"tor-{code}-retry", daemon=True).start()


def _rotator() -> None:
    """Periodically re-check that each ready location still exits where it should."""
    while not _stop.is_set():
        if _stop.wait(ROTATE_SECONDS):
            return
        for code in verified_codes():
            if _stop.is_set():
                return
            socks, _, _ = ports(code)
            got = _probe(socks)
            if got and got[1] == code:
                _set(code, exit_ip=got[0])
                _record_exit(code, got[0])
                continue
            # Drifted out of the country: drop it from the catalog rather
            # than keep serving a config that lies about where it exits.
            _set(code, verified=False, state="verifying",
                 reason="exit drifted, re-verifying")
            _reload_xray()
            if not _verify(code):
                _reload_xray()
        _retry_failed()


def start() -> None:
    """Bring every enabled location up, in the background.

    The enabled set lives in the DB (seeded from the LOCATIONS env var on
    first boot); countries activated later from the panel call start_code()
    and join the same machinery. The rotator thread runs once per boot.
    """
    codes = configured()
    if not codes:
        return
    if not available():
        db.log_event("LOCATIONS set but tor is not installed; ignoring",
                     kind="location", level="warn")
        return

    os.makedirs(TOR_DIR, exist_ok=True)
    _ensure_rotator()
    for code in codes:
        _set(code, state="pending")
        threading.Thread(target=_bring_up, args=(code,),
                         name=f"tor-{code}", daemon=True).start()


def _ensure_rotator() -> None:
    """The rotation/retry loop must run whenever any location is enabled.

    Started from both start() (boot) and start_code() (panel activation),
    because the first country may be enabled long after boot when nothing
    was configured at start time.
    """
    global _rotator_started
    if _rotator_started:
        return
    _rotator_started = True
    threading.Thread(target=_rotator, name="tor-rotate", daemon=True).start()


def shutdown() -> None:
    _stop.set()
    with _lock:
        procs = list(_procs.items())
        _procs.clear()
    for _code, p in procs:
        try:
            if p.poll() is None:
                p.send_signal(signal.SIGTERM)
        except Exception:
            pass
    for _code, p in procs:
        try:
            p.wait(timeout=5)
        except Exception:
            try:
                p.kill()
            except Exception:
                pass
