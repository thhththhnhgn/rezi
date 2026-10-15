# REALITY — VLESS + XTLS Vision (strongest bypass)

> **What it is:** REALITY makes your server *look like a real site* (e.g. `www.microsoft.com`) at TLS level — without needing that domain or any CDN. Clients see a valid-looking TLS handshake to Microsoft; DPI cannot tell it is a proxy. This is the strongest transport Xray offers.

---

## 1) Why you need it

| Situation | Works? |
|---|---|
| ISP blocks your `cdn.yourdomain.com` DNS/SNI | Cloudflare Tunnel + pinned IPs handle it |
| ISP does DPI on ClientHello and drops anything with your SNI | Smart Fragment helps |
| ISP blocks *everything* that looks like a proxy, even with Fragment | **REALITY** — mimics a whitelisted site |

REALITY does **not** need a domain, CDN, or Worker. It connects directly to your server IP on a dedicated TCP port.

---

## 2) Setup (one time)

### A. Expose a TCP port in Railway

1. Railway → your service → **Settings → Networking → Add TCP Proxy** (or **Expose Port** depending on Railway UI).
2. Set **Container Port** to `8443` (the default `REALITY_PORT` — you can change it in the panel later).
3. Railway gives you a public TCP endpoint, e.g. `switchback.proxy.rlwy.net:12345` or a raw IP:port.
   - Note the **public host + port** — you will paste the *host* into the panel, and the *port* must match.

> **Note:** Railway's HTTP edge (`*.up.railway.app` / custom domain via Cloudflare) stays as before for WS/XHTTP/etc. REALITY is a *second* listener on raw TCP — it bypasses nginx.

If Railway only offers HTTP ingress on your plan, you can still use REALITY behind Cloudflare Spectrum or on any VPS that gives you a raw TCP port. Set `REALITY_HOST` to that public host and `REALITY_PORT` accordingly.

### B. Enable in the panel

1. Open **Settings → REALITY (VLESS + XTLS Vision)**.
2. Click **Enable REALITY** → Xray generates a fresh X25519 keypair + shortId automatically and reloads.
3. (Optional) Change:
   - **Dest** — the site you mimic (default `www.microsoft.com:443`). Must be a real site that supports TLS 1.3 and is not behind your own CDN.
   - **SNI** — must match Dest's host (default `www.microsoft.com`).
   - **Fingerprint** — `chrome` is safest.
   - **Port** — must equal the Container Port you exposed (default `8443`).
   - **Public host** — leave empty to use the panel's host (`PUBLIC_HOST` / request Host). Only set this if REALITY must be reached via a different hostname/IP than the panel.

4. Hit **Save REALITY** if you changed fields. Changing **Port** triggers a reload.
5. Open any user → **Configs** → you will see a new entry **VLESS + REALITY (Direct)**. Its tag is green (`REALITY` badge).

### C. Give it to players

- **Subscription links** now include the REALITY URI automatically (one per user). Any client that updates its subscription gets it — no manual re-add.
- **QR / Copy:** use the per-config buttons as usual.
- **Clash Meta / sing-box** subscriptions also include a `REALITY` proxy with `reality-opts`.

---

## 3) Client requirements

| Client | Supports REALITY? |
|---|---|
| v2rayN / v2rayNG / NekoBox | ✅ (Xray-core) — paste the `vless://…` link |
| Clash Meta (mihomo) | ✅ — `reality-opts` in Clash config |
| sing-box 1.8+ | ✅ — `tls.reality` in sing-box config |
| Shadowrocket (iOS) | ✅ recent versions |
| Clash (plain) / old sing-box | ❌ — will ignore the entry |

If a client does not support REALITY it simply shows one extra entry that it skips — nothing breaks.

---

## 4) Environment variables (optional)

You can also configure REALITY without the panel:

```env
# Port REALITY listens on inside the container (must match Railway TCP proxy's container port)
REALITY_PORT=8443
# Public hostname clients dial for REALITY (when different from panel host)
REALITY_HOST=your-raw-ip-or-host
# Set to 1 to force-disable REALITY even if the panel says enabled
REALITY_DISABLE=0
```

Panel settings take precedence for dest/sni/fp/port/host; `REALITY_HOST`/`REALITY_PORT` env vars are the fallback.

---

## 5) Keys

- Private key, public key (`pbk`), and shortId (`sid`) are generated on first enable and stored in DB (`reality_private_key`, `reality_public_key`, `reality_short_id`).
- **Rotate:** Settings → REALITY → **Rotate keys** → Xray reloads. All old REALITY links break immediately — resend subscriptions.
- Generation prefers `xray x25519` on-disk; if missing, a fallback pair is generated so the panel stays usable offline (Xray will validate at startup).

---

## 6) Troubleshooting

| Symptom | Fix |
|---|---|
| REALITY entry shows but client says "connection refused" | The TCP port is not exposed in Railway. Add the TCP Proxy and match `reality_port`. |
| Client says "reality verification failed" | Dest/SNI must be a real site reachable from the server (try `www.microsoft.com:443`). Check `dest` and `sni` in Settings. |
| Panel says ON but no entry in subscription | `reality_enabled` is true but keys missing — click **Rotate keys** once. |
| Want to hide REALITY again | Settings → **Disable REALITY** → reload → entry disappears from all subs. |

---

## 7) Security note

REALITY's public key (`pbk`) is in every subscription link — that is by design (it is public). The **private key** never leaves the server. Rotating keys is like rotating passwords: do it if you suspect leakage.
