"""
ULTRA GAMING VPN — entrypoint.

Boots the database, seeds a first user when the DB is empty, renders the
Xray config, starts Xray + the metrics collector, then serves the control
plane API forever.
"""

from __future__ import annotations

import os
import signal
import sys
import time

from . import auth, db, links, locations, metrics, paths, server, xray


def banner() -> None:
    print(r"""
  ╦ ╦╦  ╔╦╗╦═╗╔═╗    ╔═╗╔═╗╔╦╗╦╔╗╔╔═╗
  ║ ║║   ║ ╠╦╝╠═╣    ║ ╦╠═╣║║║║║║║║ ╦
  ╚═╝╩═╝ ╩ ╩╚═╩ ╩    ╚═╝╩ ╩╩ ╩╩╝╚╝╚═╝  v3.0
""", flush=True)


def seed_pinned_ips() -> None:
    """
    First-boot bridge for the CF_IPS environment variable.

    The variable is documented in .env.example, but only the panel's
    Settings field was ever wired to the `cf_ips` setting — an admin who
    set the env var got silently nothing. Seed it once, and never overwrite
    a list the admin later edited in the panel.
    """
    raw = os.environ.get("CF_IPS", "").strip()
    if not raw:
        return
    current = db.get_setting("cf_ips", "")
    if isinstance(current, str) and current.strip():
        return
    clean = links.normalize_ips(raw)
    if not clean:
        print("[!] CF_IPS contained no public IPv4 addresses — ignored.",
              file=sys.stderr, flush=True)
        return
    db.set_setting("cf_ips", clean)
    db.log_event(f"Pinned CDN IPs seeded from CF_IPS ({clean})",
                 kind="settings")
    print(f"[+] Pinned CDN IPs: {clean}", flush=True)


def seed() -> None:
    if db.one("SELECT 1 FROM users LIMIT 1"):
        return
    name = os.environ.get("SEED_USER", "player-one")
    gb = float(os.environ.get("SEED_QUOTA_GB", "0") or 0)
    days = int(os.environ.get("SEED_DAYS", "0") or 0)
    u = db.create_user(name, quota_gb=gb, days=days, note="auto-seeded")
    print(f"[+] Seeded first user: {u['username']}", flush=True)
    print(f"    subscription: /sub/{u['sub_token']}", flush=True)


def main() -> int:
    banner()
    db.init()
    db.log_event("Control plane starting", kind="system")

    if not auth.configured():
        print("[!] ADMIN_PASS is not set — the panel will refuse all logins.",
              file=sys.stderr, flush=True)
        print("[!] Set ADMIN_PASS in Railway variables and redeploy.",
              file=sys.stderr, flush=True)

    seed()
    seed_pinned_ips()

    from . import server as _srv
    print(f"[+] Link hostnames:", flush=True)
    print(f"      primary   {_srv.PUBLIC_HOST or '(from request Host header)'}",
          flush=True)
    if _srv.RAILWAY_DOMAIN:
        print(f"      railway   {_srv.RAILWAY_DOMAIN}", flush=True)
    else:
        print("      railway   (not set — RAILWAY_PUBLIC_DOMAIN is empty)",
              flush=True)
        print("                Generate a domain in Railway, or set ALT_HOSTS",
              flush=True)
    for h in _srv.ALT_HOSTS:
        print(f"      alt       {h}", flush=True)

    print(f"[+] Transport prefix: {paths.PREFIX or '(none — legacy paths)'}",
          flush=True)
    for k, v in paths.ALL.items():
        print(f"      {k:<9} {v}", flush=True)

    if not xray.start():
        print("[!] Xray failed to start — panel stays up so you can debug.",
              file=sys.stderr, flush=True)
    else:
        print("[+] Xray online", flush=True)

    metrics.start()
    print("[+] Metrics collector online", flush=True)

    # Country exits. start() returns immediately and brings each location up
    # on its own thread, so a slow or unreachable Tor network delays the
    # locations rather than the panel.
    _locs = locations.configured()
    if _locs:
        if locations.available():
            print(f"[+] Country exits requested: {', '.join(_locs)}",
                  flush=True)
            print("    Bootstrapping in the background; each can take "
                  "minutes.", flush=True)
            print("    These route via Tor: expect 500ms+, never use them "
                  "for gaming.", flush=True)
            locations.start()
        else:
            print("[!] LOCATIONS is set but tor is not installed — ignoring.",
                  file=sys.stderr, flush=True)

    # Refresh the exit-relay country list from the Tor network in the
    # background (once per boot/day). The panel then only lists countries
    # that actually run exits.
    locations.ensure_refresh()

    def _bye(signum, frame):
        print("\n[+] Shutting down...", flush=True)
        metrics.shutdown()
        locations.shutdown()
        xray.stop()
        db.log_event("Control plane stopped", kind="system")
        sys.exit(0)

    signal.signal(signal.SIGTERM, _bye)
    signal.signal(signal.SIGINT, _bye)

    print(f"[+] API listening on {server.BIND[0]}:{server.BIND[1]}", flush=True)
    server.serve()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
