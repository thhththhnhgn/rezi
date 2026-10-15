<div align="center">

# ⚡ ULTRA GAMING VPN v3

**A gaming-tuned Xray control panel that deploys to Railway in one click.**

Multi-user · per-user quotas & traffic accounting · ranks and achievements ·
latency race · subscription links for every client · secret transport paths ·
decoy website · PWA · English / فارسی

</div>

---

## What this is

A single Docker image that runs **Xray-core**, **nginx** and a **Python control
plane** together. It gives you:

* a **neon gaming admin panel** at `/panel/`
* a **player portal** at `/u/<token>/` that each user can open on their phone
* **subscription URLs** in v2rayN, Clash Meta and sing-box formats
* real **per-user traffic accounting** pulled from Xray's own stats API
* automatic **quota and expiry enforcement**
* **five transports** on one HTTPS port, all behind one secret path prefix

Everything is stdlib Python and vanilla JS — no build step, no npm install,
no external services.

---

## Table of contents

1. [Quick start](#quick-start)
2. [Environment variables](#environment-variables)
3. [Persisting your data](#persisting-your-data)
4. [Using the panel](#using-the-panel)
5. [Connecting a client](#connecting-a-client)
6. [Cloudflare Worker (optional)](#cloudflare-worker-optional)
7. [Game profiles](#game-profiles)
8. [Console commands](#console-commands)
9. [How it works](#how-it-works)
10. [Railway limitations](#railway-limitations-read-this)
11. [Troubleshooting](#troubleshooting)
12. [Security notes](#security-notes)
13. [Development](#development)

---

## Quick start

### 1. Push this repository to your own GitHub account

```bash
git clone <this-repo>
cd panel.gaming
git remote set-url origin https://github.com/<you>/<your-repo>.git
git push -u origin main
```

### 2. Create the Railway service

1. Go to [railway.app](https://railway.app) → **New Project** →
   **Deploy from GitHub repo**
2. Pick your repository. Railway detects the `Dockerfile` automatically.
3. Wait for the first build (it downloads the latest Xray-core, ~2 minutes).

### 3. Generate your secrets

Run these three commands locally and keep the output:

```bash
openssl rand -hex 32   # -> SECRET_KEY
openssl rand -hex 16   # -> PATH_SECRET
openssl rand -base64 24 # -> ADMIN_PASS
```

No `openssl`? Use Python:

```bash
python3 -c "import secrets; print('SECRET_KEY =', secrets.token_hex(32)); print('PATH_SECRET =', secrets.token_hex(16)); print('ADMIN_PASS  =', secrets.token_urlsafe(18))"
```

### 4. Set the variables

In Railway open your service → **Variables** → **Raw Editor**, and paste:

```env
ADMIN_USER=admin
ADMIN_PASS=<the password you generated>
SECRET_KEY=<the 64-char hex you generated>
PATH_SECRET=<the 32-char hex you generated>
DB_PATH=/data/ultra.db
```

> ⚠️ **`ADMIN_PASS` is mandatory.** Without it the panel refuses every login,
> by design. `PATH_SECRET` is what hides your tunnel from scanners — always
> set it.

### 5. Add a volume (strongly recommended)

Railway containers have an ephemeral filesystem. Without a volume you lose
every player, quota and statistic on each redeploy.

**Service → Settings → Volumes → New Volume**

| Field | Value |
|-------|-------|
| Mount path | `/data` |

Size 1 GB is plenty — the database stays a few megabytes even with hundreds
of players.

### 6. Generate a domain

**Service → Settings → Networking → Generate Domain.**

Railway gives you something like `my-app-production-a1b2.up.railway.app`.
TLS is handled by Railway, so everything is HTTPS out of the box.

### 7. Open the panel

```
https://<your-domain>/panel/
```

Log in with `ADMIN_USER` / `ADMIN_PASS`.

Visiting the bare domain shows an innocuous "cloud rendering company" page —
that's the decoy, and it's intentional.

---

## Environment variables

### Required

| Variable | Description |
|----------|-------------|
| `ADMIN_PASS` | Admin panel password. Logins are rejected until this is set. |
| `SECRET_KEY` | Signs session tokens. 64 hex characters. If unset, a random one is generated per boot, which logs everyone out on redeploy. |
| `PATH_SECRET` | Derives the secret URL prefix for all tunnels. **Leaving this empty exposes predictable `/vless`, `/vmess`… paths.** |

### Recommended

| Variable | Default | Description |
|----------|---------|-------------|
| `ADMIN_USER` | `admin` | Admin username. |
| `DB_PATH` | `/data/ultra.db` | SQLite location. Point at your mounted volume. |
| `CF_WORKER_HOST` | — | Worker hostname (no `https://`). Adding it makes the panel emit CF variants of every config. |

### Optional

| Variable | Default | Description |
|----------|---------|-------------|
| `PUBLIC_HOST` | auto | Force the hostname used in generated links. Normally detected from the request. |
| `ALT_HOSTS` | — | Extra hostnames to also emit configs for, comma separated. Railway's own `*.up.railway.app` name is added automatically. |
| `PATH_PREFIX` | — | Pin a readable prefix instead of the derived hash, e.g. `media` → `/media/xhttp`. |
| `SEED_USER` | `player-one` | First player created on an empty database. |
| `SEED_QUOTA_GB` | `0` | Quota for the seeded player, `0` = unlimited. |
| `SEED_DAYS` | `0` | Validity for the seeded player, `0` = never expires. |
| `SESSION_TTL` | `86400` | Admin session lifetime in seconds. |
| `XRAY_LOGLEVEL` | `warning` | `debug`, `info`, `warning`, `error`, `none`. |
| `PORT` | `8080` | Set automatically by Railway. Don't override. |

A copy-pasteable list lives in [`.env.example`](.env.example).

---

## Persisting your data

The SQLite database holds players, credentials, quotas, traffic history,
achievements and settings. It lives at `DB_PATH`.

* **With a volume at `/data`** — everything survives redeploys. ✅
* **Without a volume** — `start.sh` detects that `/data` is not writable,
  falls back to `/tmp/ultra.db` and prints a loud warning. Every redeploy
  wipes your players.

To back up, open the console page in the panel and run `users`, or hit
`/api/export?format=json` with your admin token.

---

## Using the panel

### Dashboard
Live CPU, memory, sessions and uptime; a throughput graph; the **Gaming
Score** gauge (one 0–100 number combining CPU, memory, load average and
session pressure); top players; and the event log.

### Players
Create, edit, suspend and delete accounts. Each player gets a UUID, a Trojan
password and a subscription token — all rotatable from the
**Rotate keys** button.

Per player you can set:
* **Quota** in GB (`0` = unlimited) — the account is auto-suspended at 100 %
* **Expiry** in days (`0` = never) — auto-suspended when it lapses
* **Note** — free text for your own reference

The **Configs** button opens every share link, a QR code for each, all three
subscription URLs and the player's achievements.

### Analytics
History over 1 h / 6 h / 24 h / 7 d / 30 d, a weekday × hour traffic heatmap,
and the XP leaderboard.

### Latency Race
Probes each available route eight times, then reports median RTT, jitter and
packet loss, and crowns the fastest. Runs from *your* browser, so it measures
the path you actually care about.

### Console
A real terminal against the server. Type `help`.

### Settings
* **Turbo mode** — rebuilds the Xray config with zero buffering, shorter idle
  timeouts and a faster handshake, then reloads. Best for competitive play.
* Your secret transport paths, so you can verify them.
* CPU and quota alert thresholds.

---

## Connecting a client

### Every subscription carries both hostnames

A deployment usually answers on two names: your custom domain and the
original `*.up.railway.app` one. Both are emitted, so a subscription contains
one config per protocol **per host** — ten entries instead of five. If one
name stops resolving for a player's ISP, the other is already in their client
and they just switch to it.

Railway's own name comes from `RAILWAY_PUBLIC_DOMAIN`, but **Railway only
sets that variable once the service actually has a generated
`*.up.railway.app` domain**. A service that was only ever given a custom
domain will not have it, and the subscription will silently contain just the
one hostname.

Two ways to fix that:

* Railway → Settings → Networking → **Generate Domain**, then redeploy, or
* set `ALT_HOSTS=your-app.up.railway.app` manually.

The Settings page lists every hostname currently in use and warns when only
one is active, so you do not have to read deploy logs to notice. Private and
loopback addresses are filtered out, so an internal `Host` header can never
produce a dead config.

### Quota and expiry inside the client

Every client reads the `Subscription-Userinfo` header, but most bury it in a
details pane. The subscription body therefore starts with two extra entries
that show the same numbers directly in the server list:

```
📊 32.00GB / 100.00GB  (32%)  ·  68.00GB left
⏳ 29 days left  ·  2026-08-30
```

They point at `127.0.0.1:1`, so they are visibly informational and fail
instantly if something tries to dial them. Append `?info=0` to the
subscription URL to leave them out.

### Easiest: subscription URL

Give the player their portal link:

```
https://<your-domain>/u/<sub_token>/
```

They pick their game profile, tap **Copy** on a subscription URL and paste it
into their app. The app then keeps every config up to date by itself.

| Client | Format to use |
|--------|---------------|
| v2rayNG, v2rayN, NekoBox, Shadowrocket | default (Base64) |
| Clash Meta, Clash Verge, FlClash | `?format=clash` |
| sing-box, SFA, SFI | `?format=singbox` |

### Manual: single config

Copy any link from the panel or portal, or scan its QR code.

### Which transport should I pick?

| Transport | When to use |
|-----------|-------------|
| **VLESS + XHTTP** ⭐ | Default. Newest transport, lowest overhead, best latency. |
| **VLESS + HTTPUpgrade** | Lighter than WebSocket, very good on mobile networks. |
| **VLESS + WebSocket** | Maximum client compatibility. Use if something else fails. |
| **Trojan + WS** | Alternative fingerprint if VLESS is disrupted. |
| **VMess + WS** | Legacy clients. |

---

## Custom domain (recommended)

Railway's `*.up.railway.app` is widely blocked. Pointing your own domain at
the deployment fixes that, hides the origin behind Cloudflare, and lets you
swap the hostname later without reissuing anyone's subscription.

**Short version:**

1. Railway → Settings → Networking → **+ Custom Domain** → `cdn.yourdomain.com`
2. In Cloudflare DNS add both records Railway shows — the **CNAME** and the
   **TXT** — with the proxy **grey (DNS only)** for now
3. Wait for Railway's green tick (the certificate)
4. Cloudflare → SSL/TLS → set mode to **Full** (never *Flexible* — it causes
   a redirect loop; *Full strict* breaks on renewal)
5. Flip the CNAME proxy to **orange**
6. Railway → Variables → `PUBLIC_HOST=cdn.yourdomain.com`
7. Re-copy every config from the panel

**Cloudflare settings that matter:**

| Section | Setting | Value |
|---------|---------|-------|
| Network | **WebSockets** | **On** — without it VLESS/VMess/Trojan cannot connect |
| Network | gRPC, HTTP/2, HTTP/3 | On |
| Speed | **Rocket Loader** | **Off** — it rewrites the panel's JS |
| Speed | **Auto Minify** | **Off** |
| SSL/TLS | Mode | **Full** |

Use a one-level subdomain (`cdn.yourdomain.com`). Deeper names such as
`vpn.cdn.yourdomain.com` need Cloudflare's paid Advanced Certificate Manager.

The full walkthrough, including the Worker-on-your-domain variant and a
troubleshooting table, is in [`docs/دامنه-شخصی.md`](docs/دامنه-شخصی.md).

---

## Cloudflare Worker (optional)

A worker gives you a second entry point on Cloudflare's network. It can be
faster than the Railway edge and gives you a hostname to switch to if the
Railway domain is disrupted.

The bundled [`cloudflare-worker.js`](cloudflare-worker.js) is a **real
WebSocket relay** — the previous version used a plain `fetch()`, which
silently dropped every WS tunnel.

1. Cloudflare dashboard → **Workers & Pages** → **Create Worker**
2. Replace the code with the contents of `cloudflare-worker.js`, **Deploy**
3. **Settings → Variables**, add:

   | Name | Value |
   |------|-------|
   | `UPSTREAM` | `your-app.up.railway.app` (no `https://`) |
   | `PATH_PREFIX` | the prefix shown on the panel's Settings page |
   | `FALLBACKS` | *(optional)* comma-separated backup hosts |

4. Verify: `https://<worker>.workers.dev/ping` → `pong`, and
   `https://<worker>.workers.dev/__status` → JSON with `"reachable": true`
5. Put the worker hostname into Railway's `CF_WORKER_HOST` and redeploy.

CF variants now appear next to every config in the panel.

### Pinned CDN IPs (آیپی ثابت)

When an ISP blocks your hostname's DNS/SNI, configs that keep the hostname
as SNI but dial a fixed CDN IP still connect (the CDN routes by SNI). Set
`CF_IPS=104.16.132.229,104.17.24.14` or use **Settings → Pinned CDN IPs**
in the panel, and every subscription gains two `⚡IP1/IP2...` configs per
IP (HTTPUpgrade + WS) that use the IP as the server address while SNI/Host
stay your domain. Only helps when the hostname is proxied through
Cloudflare; the SNI itself can never be a foreign site, because TLS is
terminated for your hostname — see `docs/آیپی-ثابت-کلادفلر.md`.

---



## Country exits — only countries with Tor exit relays

The **Locations** page lists only the countries where Tor actually runs
exit relays — live data from onionoo.torproject.org, refreshed at boot and
daily, with a bundled snapshot (dated) as the offline fallback. Each card
shows the flag, the name and the running exit-relay count; countries with
a handful of relays are marked "scarce" because they rarely verify.
Palestine, for example, has zero relays and is not listed at all. A small
hostile/censored block (Iran, China, Russia, North Korea, Syria, Cuba,
Venezuela, Belarus and the Central-Asian block) is hidden by default and
overridable via `LOCATION_EXCLUDE`. Each country is its own card:

* **Activate / Deactivate** per country, at runtime — no redeploy. A
  country boots its own Tor instance (≈40 MB), verifies its exit country,
  and only then appears in subscriptions. A `MAX_LOCATIONS` cap (default
  10) stops you from exhausting the container's RAM.
* **Best exit IPs** — every country card tracks the exit IPs it has
  actually served and ranks the five most stable ones (share of tracked
  time, session count). Tor rotates exits on its own, so this is the
  honest answer to "which exits can I rely on".
* **فارسی** — when the panel language is فارسی, country names are shown in
  Persian (with their flag) and the search box matches Persian names too.
* **📌 Pin** — Tor's `ExitNodes` accepts a bare IP, so pinning forces every
  circuit through one relay, giving you a fixed exit IP for a
  region-locked service. It comes with a real cost: if that relay goes
  down the location fails until unpinned — the panel warns before pinning
  and makes unpinning one click.

`LOCATIONS` still works as the first-boot seed; after that the database
owns the list.

## Stability and measurement

* **Xray watchdog** — if Xray dies, the metrics loop brings it back
  automatically (45 s grace, one attempt per 5 minutes, event-logged), so
  a dead tunnel no longer waits for a redeploy.
* **Tor fail-fast** — each country's torrc now forces IPv4 only (Railway
  has no IPv6 egress, so AAAA attempts only add delay) and gives up on
  dead SOCKS targets quickly (SocksTimeout 30s, capped circuit build), so
  a stalled circuit is retried instead of hanging the tunnel.
* **Smart Fragment** — Settings → Smart Fragment adds anti-DPI TLS
  ClientHello fragmentation (light/medium/aggressive) to every vless
  link, the standard way past SNI-based DPI on strict operators. v2rayNG
  / NekoBox / v2rayN only.
* **Hardened routing** — the tunnel cannot reach RFC1918 ranges, so
  Railway's internal 172.x network is out of reach; main inbounds now
  carry TCP keepalive so wedged nginx↔Xray sockets are detected fast.
* **WebSocket echo** — the **Latency Race** page gained a "Tunnel WS"
  measurement: it opens a real WebSocket through the same path a game
  session uses (TLS → Cloudflare → nginx) and times round trips over it,
  which is closer to actual in-game latency than an HTTP probe.

---

## Game profiles

Profiles change **client-side** transport hints baked into the generated
links — mux, fragmentation, keepalive and which transport is offered first.

| Profile | Tuned for |
|---------|-----------|
| ⚖️ **Balanced** | Everyday use. Safe defaults. |
| 🎯 **Valorant / CS2** | Tac-shooters. Mux off, tick-accurate. |
| 🔫 **PUBG / COD Mobile** | Mobile BR. Fragmentation for flaky cellular. |
| 🏹 **Fortnite / Apex** | Fast BR with heavy asset streaming. |
| 🛡️ **LoL / Dota / Wild Rift** | MOBA. Stable long sessions, jitter-averse. |
| ⚽ **FC Mobile / eFootball** | Football sims. Jitter matters more than raw ping. |
| 👑 **Clash Royale / CoC** | Supercell titles. Tiny packets, long idle sessions. |
| 💥 **Brawl Stars** | Fast 3v3. Mux off so a stall never blocks a stream. |
| 🥷 **Stealth** | Maximum DPI evasion. Slower but gets through. |
| 📺 **Streaming** | Throughput first. Big buffers, high concurrency. |

Switch profiles in the config modal or the player portal; links regenerate
instantly.

---

## Game server ping

The **Game Ping** page (and the same panel in the player portal) measures
round-trip time from *your browser* to each publisher's edge — Riot, Steam,
EA, Konami, Supercell, Tencent, Epic, Moonton and more.

Run it once with the tunnel off and once with it on: the difference is
exactly what the VPN costs you for that title.

Colour coding: green under 60 ms, teal under 120 ms, amber under 200 ms,
red above.

---

## Boost

Any player can trigger a **30-minute boost**, from the panel or their own
portal. While it is running, that account is moved onto a separate Xray
policy level with:

* zero buffering (`bufferSize: 0`)
* the fastest handshake window
* the longest idle tolerance

A live countdown shows in both the panel and the portal, and the account
returns to normal automatically when it expires.

---

## Weekly report

Every player has a shareable week-in-review: total traffic, daily average,
change against the previous week, a seven-day bar chart, busiest day and
hour, rank progress, achievements, and a projection of how long the
remaining quota will last at the current rate.

Open it from the 📊 button next to any player, or from the player's own
portal.

---

## Trial links

Create a trial link and anyone who opens it gets a working account
instantly — no admin involvement.

**Trial Links** page → **New trial link**, then choose:

| Setting | Meaning |
|---------|---------|
| Quota | Data allowance per claimed account |
| Duration | How long each account lives, in hours |
| Total claims | How many accounts the link can ever create |
| Per day | Daily cap across all visitors |

Abuse controls: one claim per IP per 24 hours, a hard daily cap, a lifetime
cap, and a pause switch. Claimed accounts get random unguessable usernames
and expire to the hour.

---

## Themes

Seven built-in themes plus a custom colour picker, selectable from
**Settings** in the panel and from the player portal:

**Neon** (default) · **Matrix** · **Cyberpunk** · **Ice** · **Ember** ·
**Royal** · **Stealth**

*Stealth* also disables the particle background, scanlines and logo
animation — useful when you would rather the screen not look like a VPN
panel at a glance.

The choice is stored per browser and applies before first paint, so there
is no colour flash on load.

---

## Console commands

```
help                 show all commands
stats                live system snapshot
score                gaming health score
users [n]            list players
user <name|id>       player detail
add <name> [gb] [d]  create a player
del <name|id>        delete a player
enable  <name|id>    re-activate a player
disable <name|id>    suspend a player
reset <name|id>      rotate credentials
top [n]              biggest consumers
events [n]           recent events
turbo on|off         low-latency mode
reload               restart Xray
paths                show transport paths
uptime               server uptime
clear                clear the console
```

Arrow keys scroll through history.

---

## Latency and stability tuning

Every default here is chosen for the lowest possible delay rather than for
throughput benchmarks.

**Server (Xray)**

| Setting | Value | Why |
|---------|-------|-----|
| `bufferSize` | `4` normal / `0` turbo & boost | Speed build: normal traffic is buffered (4 MB/conn) so downloads saturate the pipe; Turbo mode and per-user Boost switch to zero-buffer for minimum latency. |
| `domainStrategy` | `AsIs` | Skips a DNS resolution on **every** new connection that `IPIfNonMatch` forces. |
| `queryStrategy` | `UseIPv4` | Railway has no usable IPv6 egress; asking for AAAA only adds a timeout. |
| `connIdle` | 600 s | Games hold TCP open through long silent gaps. Short timeouts are the classic cause of random disconnects. |
| `uplinkOnly` / `downlinkOnly` | `0` | A half-closed connection is never torn down while the other direction is still live. |
| sniffing | **off** | With `destOverride` the server rewrites each connection's destination and re-resolves it, discarding the game's chosen edge IP. |
| `tcpNoDelay` | on | Nagle off, so small game packets leave immediately. |
| `tcpFastOpen` | on | First data segment rides along with the handshake instead of waiting a round trip. |
| `tcpUserTimeout` | 10 s | A stalled route fails fast and reconnects instead of appearing frozen. |
| `tcpcongestion` | `bbr` | Reaches full throughput far quicker than cubic on lossy mobile links. |
| `tcpMaxSeg` | 1400 | Stays under the common 1500-byte MTU so packets are never fragmented mid-path. |

**XHTTP**

| Setting | Value | Why |
|---------|-------|-----|
| `mode` | `packet-up` | The only mode nginx forwards intact. `stream-one` needs streamed H2 uploads that `proxy_pass` drops. |
| `scMinPostsIntervalMs` | `1-3` | Speed build: uploads flush after 1-3 ms (stock default is 30 ms), so packets barely wait for their slot. |
| `scMaxEachPostBytes` | `200000-500000` | Bigger, denser posts move more data per second while still flushing fast. |
| `scMaxBufferedPosts` | 60 | Slack for out-of-order POSTs on cellular. |

**nginx**

| Setting | Why |
|---------|-----|
| `tcp_nodelay on` | Without it nginx coalesces the small frames a game produces. |
| `proxy_request_buffering off` | For a tunnel the body *is* the tunnel, so buffering it buffers the session. |
| `proxy_buffering off` | Same, in the other direction. |
| `proxy_socket_keepalive on` | nginx must never be the component that drops a live tunnel. |

**Client links**

| Setting | Why |
|---------|-----|
| `alpn=h2,http/1.1` on every transport | Both ALPNs offered everywhere; the client negotiates h2 when it helps (XHTTP, parallel downloads) and http/1.1 otherwise. |
| `fp=random` on every link | Randomized TLS fingerprint beats a fixed chrome fingerprint for DPI evasion. |
| `?ed=2560` on every WebSocket path | Early data carries the first packet inside the upgrade request, saving a full round trip on every new connection. |
| `scy=aes-128-gcm` on VMess | Naming the cipher skips runtime negotiation; every modern ARM core has AES in hardware. |
| No fragmentation on gaming profiles | Splitting the ClientHello and sleeping between pieces is an anti-DPI trick with a real latency cost. Only the stealth profile pays it. |

**Turbo mode** additionally shortens the handshake window. **Boost** applies
the same treatment to one player for 30 minutes.

---

## How it works

```
                      ┌── Railway edge (terminates TLS) ──┐
  player ── HTTPS ───►│                                    │
                      └──────────────┬─────────────────────┘
                                     │ :$PORT
                          ┌──────────▼──────────┐
                          │        nginx        │
                          └──┬───────────────┬──┘
        secret prefix        │               │   /panel/  /u/  /api/  /sub/
     /<hash>/xhttp  ─────────┤               ├──────────────┐
     /<hash>/vless  ─────────┤               │              │
     /<hash>/vmess  ─────────┤               │   everything else → decoy site
     /<hash>/trojan ─────────┤               │
     /<hash>/upgrade ────────┤               │
     /<hash>/ss     ─────────┤               │
                             ▼               ▼
                   ┌──────────────┐   ┌──────────────────┐
                   │  Xray-core   │   │  control plane   │
                   │ :7001–:7005  │◄──┤  (Python, :8888) │
                   │  api :10085  │   │  SQLite + API    │
                   └──────────────┘   └──────────────────┘
```

* **`start.sh`** renders `nginx.conf.template` with Railway's `$PORT` and your
  secret prefix, validates it with `nginx -t`, then supervises both processes.
* **`app/main.py`** boots the database, writes the Xray config, starts Xray and
  the metrics collector, and serves the API.
* **`app/metrics.py`** samples `/proc` every 2 s, persists a row every 60 s, and
  every 20 s pulls per-user counters from Xray's stats API (resetting them),
  folds them into the database, awards XP and achievements, and enforces
  quotas and expiry.
* **`app/xray.py`** renders the Xray config from the database. Adding a player
  validates the new config into a temp file *before* touching the live one, so
  a bad config can never take your server down.

### Project layout

```
app/
  main.py       entrypoint
  server.py     HTTP API (stdlib ThreadingHTTPServer)
  db.py         SQLite schema and helpers
  xray.py       config generation + process control + stats
  metrics.py    background collector
  links.py      share links, Clash / sing-box generators
  gamify.py     ranks, XP, achievements
  profiles.py   per-game tuning presets
  paths.py      secret path derivation
  auth.py       HMAC sessions, brute-force throttling
web/
  panel/        admin panel
  u/            player portal
  public/       decoy site
  assets/       css, core.js, panel.js, qr.js (self-contained QR encoder)
  sw.js         service worker (PWA)
tests/
  test_all.py   149-check end-to-end suite
```

---

## Railway limitations (read this)

Railway shapes what is technically possible. These are not bugs:

| Not available | Why |
|---------------|-----|
| **Hysteria2, TUIC** | Railway does not route UDP. UDP-based protocols cannot work. |
| **REALITY** | Railway terminates TLS at its edge, so Xray never sees the raw handshake REALITY needs. |
| **XTLS Vision** | Same reason — it requires direct control of the TLS connection. |
| **Custom domains on the free tier** | Railway's own `*.up.railway.app` is used instead. |

What compensates: secret path prefixes, a decoy site, XHTTP packet-up (which
traverses buffering middleboxes), fragmentation profiles and the Cloudflare
Worker as a second entry point.

---

## Troubleshooting

<details>
<summary><b>The panel says "ADMIN_PASS is not set"</b></summary>

Add `ADMIN_PASS` in Railway → Variables and redeploy. The panel deliberately
refuses all logins until it's set.
</details>

<details>
<summary><b>Deploy logs show "not writable, falling back to /tmp"</b></summary>

You have no volume mounted at `/data`. Add one
(Settings → Volumes → mount path `/data`) or set `DB_PATH` to a writable
location. Without it, players vanish on every redeploy.
</details>

<details>
<summary><b>Xray shows OFFLINE in the panel</b></summary>

Open the Console page and run `reload` — it prints the validation error.
The panel intentionally stays up when Xray is down so you can debug.
Common causes: a corrupted database, or a build where the Xray download
failed (rebuild to fix).
</details>

<details>
<summary><b>A config connects but no traffic flows</b></summary>

1. Confirm the **path prefix** in the client matches Settings → Transport paths.
2. Try **HTTPUpgrade** or **WebSocket** instead of XHTTP — some networks
   mangle streamed POSTs.
3. Check the client uses **port 443** and **TLS on** with SNI = your domain.
4. Regenerate the link after any `PATH_SECRET` change — old links break by design.
</details>

<details>
<summary><b>Everything broke after I changed PATH_SECRET</b></summary>

That's the point: changing it rotates every path. Redistribute the
subscription links (or tell players to refresh — subscription URLs keep
working, only manual configs need re-copying).
</details>

<details>
<summary><b>Cloudflare Worker returns 404 for tunnels</b></summary>

`PATH_PREFIX` in the worker must exactly match the panel's prefix, including
the leading slash. Check `https://<worker>.workers.dev/__status`.
</details>

<details>
<summary><b>WebSocket via the worker disconnects instantly</b></summary>

Make sure you deployed the **current** `cloudflare-worker.js`. Older versions
used a plain `fetch()` which cannot relay WebSockets.
</details>

<details>
<summary><b>A player hit their quota and can't connect</b></summary>

They were auto-suspended. In the panel edit them, raise the quota (or tick
**Reset traffic counters**) and set status back to Active.
</details>

<details>
<summary><b>Traffic numbers stay at zero</b></summary>

Counters sync every 20 seconds and only count traffic that actually flowed
through Xray. If they never move, Xray is probably offline — see above.
</details>

---

## Security notes

* The admin password is compared in constant time; eight failed logins from
  one IP trigger a five-minute lockout, and nginx rate-limits `/api/login`
  to 10 requests per minute.
* Session tokens are HMAC-SHA256 signed and carry an expiry. They are not
  encrypted — don't paste them anywhere public.
* The player portal deliberately exposes only that player's own data. Trojan
  passwords and internal IDs are never sent to it.
* Subscription tokens are bearer credentials. Anyone holding one can fetch
  that player's configs — rotate with **Rotate keys** if one leaks.
* Everything except the panel, portal, API and tunnel paths returns the decoy
  page, so the deployment does not look like a proxy from outside.
* The Xray routing table blocks BitTorrent and refuses to route back into
  `127.0.0.1`, so the tunnel cannot be used to reach the control plane.

---

## Development

```bash
# run the whole test suite (149 checks, no Docker needed)
python3 tests/test_all.py

# run the control plane locally
export DB_PATH=/tmp/dev.db ADMIN_PASS=dev PATH_SECRET=dev \
       XRAY_BIN=/nonexistent XRAY_CONFIG=/tmp/dev-xray.json
python3 -m app.main
# panel API on http://127.0.0.1:8888 (serve web/ separately, or use Docker)

# build the real image
docker build -t ultra-gaming .
docker run -p 8080:8080 -e ADMIN_PASS=dev -e PATH_SECRET=dev ultra-gaming
# then open http://localhost:8080/panel/
```

The test suite stubs out the Xray binary, so it runs anywhere Python 3.11+ is
available. It covers authentication, player CRUD, every subscription format,
quota and expiry enforcement, Xray config generation, the console, exports and
input hardening.

---

<div align="center">
<sub>Built for Railway · Xray-core · no dependencies · MIT</sub>
</div>
