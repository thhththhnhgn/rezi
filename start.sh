#!/bin/bash
# ULTRA GAMING VPN — container entrypoint
#
# 1. Apply TCP/kernel tuning for gaming
# 2. Render nginx.conf with Railway's dynamic $PORT and the secret path prefix
# 3. Start the Python control plane (which owns Xray + metrics)
# 4. Start nginx in the foreground, supervising both
set -uo pipefail

PORT="${PORT:-8080}"
API_PORT="${API_PORT:-8888}"
export API_PORT

echo "════════════════════════════════════════════════"
echo "  ULTRA GAMING VPN v3 — booting"
echo "  edge port : ${PORT}"
echo "  data dir  : ${DB_PATH:-/data/ultra.db}"
echo "════════════════════════════════════════════════"

# ── TCP/kernel tuning for gaming ──────────────────────────────────────
# Apply sysctl values if /proc/sys is writable (some containers allow it).
# On Railway it's usually read-only, so this is best-effort.
if [ -f /etc/sysctl.d/99-gaming.conf ]; then
  while IFS='=' read -r key val; do
    key=$(echo "$key" | xargs)
    val=$(echo "$val" | xargs)
    [ -z "$key" ] && continue
    [[ "$key" == \#* ]] && continue
    echo "$val" > "/proc/sys/${key//./\/}" 2>/dev/null || true
  done < /etc/sysctl.d/99-gaming.conf
  echo "[+] TCP tuning applied (best-effort)"
fi

# File descriptor limits for high connection count
ulimit -n 65535 2>/dev/null || true

# Set process priority: slightly favor Xray and nginx over the control plane
# (nice -5 = slightly higher priority, nice 5 = slightly lower)
renice -5 $$ 2>/dev/null || true

# ── Resolve the secret transport prefix from Python (single source of truth)
PREFIX="$(python3 -c 'from app import paths; print(paths.PREFIX)' 2>/dev/null || echo '')"
if [ -n "$PREFIX" ]; then
  echo "[+] Transport prefix: ${PREFIX}"
else
  echo "[!] PATH_SECRET not set — using legacy predictable paths (/vless, /vmess...)"
  echo "[!] Set PATH_SECRET in Railway to hide the tunnel behind a random prefix."
fi

# ── Stamp the build into the web assets ───────────────────────────────
APP_VERSION="$(python3 -c 'from app import __version__; print(__version__)' 2>/dev/null || echo dev)"
BUILD_ID="${RAILWAY_DEPLOYMENT_ID:-$(date +%s)}"
STAMP="${APP_VERSION}-${BUILD_ID:0:8}"
echo "[+] Build stamp: ${STAMP}"

WEBROOT=/usr/share/nginx/web
if [ -d "$WEBROOT" ] && [ -w "$WEBROOT" ]; then
  find "$WEBROOT" -name '*.html' -type f -exec \
    sed -i -E "s#(/assets/[a-z]+\.(css|js))\?v=[^\"]*#\1?v=${STAMP}#g" {} + 2>/dev/null || true
  # Keep the JS constant in sync so the panel can detect a stale bundle.
  sed -i -E "s#var ASSET_VERSION = \"[^\"]*\"#var ASSET_VERSION = \"${STAMP}\"#" \
    "$WEBROOT/assets/panel.js" 2>/dev/null || true
fi

# ── Render nginx config ───────────────────────────────────────────────
mkdir -p /etc/nginx/snippets /run/nginx /var/lib/nginx/tmp /var/log/nginx

# One location block per KNOWN country exit. Python owns the country list
# and the port arithmetic so the two can never disagree; this only formats
# what it reports.
LOCATION_BLOCKS="$(python3 - <<'PYEOF' 2>/dev/null || true
from app import locations
out = []
for code in locations.known_codes():
    port = locations.ports(code)[2]
    out.append(
        f"        location {locations.path_for(code)} {{\n"
        f"            proxy_pass         http://127.0.0.1:{port};\n"
        f"            include            /etc/nginx/snippets/ws.conf;\n"
        f"        }}"
    )
print("\n".join(out))
PYEOF
)"

if [ -n "$LOCATION_BLOCKS" ]; then
  echo "[+] Country exits routed: $(echo "$LOCATION_BLOCKS" | grep -c '^        location') countries"
fi

# awk, not sed: the replacement is multi-line and sed would need every
# newline escaped. Passing it as a variable also avoids re-interpreting
# any regex metacharacter that appears in a path.
sed -e "s|__PORT__|${PORT}|g" \
    -e "s|__PREFIX__|${PREFIX}|g" \
    /app/nginx.conf.template \
  | awk -v blocks="$LOCATION_BLOCKS" \
      '{ if ($0 == "__LOCATIONS__") print blocks; else print }' \
  > /etc/nginx/nginx.conf

if ! nginx -t -c /etc/nginx/nginx.conf 2>/tmp/nginx-test.log; then
  echo "[!] nginx configuration is invalid:"
  cat /tmp/nginx-test.log
  exit 1
fi
echo "[+] nginx config OK"

# ── Ensure the data directory exists (Railway volume mounts at /data) ──
mkdir -p "$(dirname "${DB_PATH:-/data/ultra.db}")" 2>/dev/null || true
if ! touch "$(dirname "${DB_PATH:-/data/ultra.db}")/.write-test" 2>/dev/null; then
  echo "[!] ${DB_PATH:-/data/ultra.db} is not writable."
  echo "[!] Attach a Railway volume at /data, or set DB_PATH to a writable path."
  echo "[!] Falling back to /tmp/ultra.db — DATA WILL BE LOST ON REDEPLOY."
  export DB_PATH=/tmp/ultra.db
else
  rm -f "$(dirname "${DB_PATH:-/data/ultra.db}")/.write-test"
fi

# ── Start the control plane ───────────────────────────────────────────
echo "[+] Starting control plane..."
python3 -u -m app.main &
API_PID=$!

# Wait for the API to answer before letting nginx take traffic
for i in $(seq 1 40); do
  if curl -fsS "http://127.0.0.1:${API_PORT}/health" >/dev/null 2>&1; then
    echo "[+] Control plane ready (${i}00ms)"
    break
  fi
  if ! kill -0 "$API_PID" 2>/dev/null; then
    echo "[!] Control plane died during startup."
    exit 1
  fi
  sleep 0.25
done

# ── Cloudflare Tunnel (automatic extra host, no user action) ─────────
# Gives every subscription an additional hostname (xxx.trycloudflare.com)
# via a QUIC tunnel from the container to Cloudflare. If the primary domain
# is blocked, this one still works. `trycloudflare.com` is a Cloudflare-owned
# anycast domain — blocking it breaks a huge slice of the internet, so it
# survives far longer than a single custom domain.
#
# Two modes:
#   * TUNNEL_TOKEN set  -> named tunnel (stable hostname, from dashboard)
#   * otherwise         -> quick tunnel (ephemeral, no account needed)
# Disable entirely with TUNNEL_DISABLE=1.

TUNNEL_FILE="${TUNNEL_FILE:-/tmp/tunnel_host}"
CLOUDFLARED_PID=""
CLOUDFLARED_BIN="${CLOUDFLARED_BIN:-/usr/local/bin/cloudflared}"
rm -f "$TUNNEL_FILE" /tmp/cloudflared.log

if [ "${TUNNEL_DISABLE:-0}" = "1" ]; then
  echo "[ ] Tunnel disabled via TUNNEL_DISABLE=1"
elif [ -n "${TUNNEL_TOKEN:-}" ] && [ -x "$CLOUDFLARED_BIN" ]; then
  echo "[+] Starting cloudflared named tunnel..."
  # TUNNEL_HOST may be set alongside the token to publish the known hostname
  # immediately; otherwise the dashboard hostname is used.
  if [ -n "${TUNNEL_HOST:-}" ]; then
    printf '%s' "$TUNNEL_HOST" > "$TUNNEL_FILE"
    chmod 600 "$TUNNEL_FILE" 2>/dev/null || true
    echo "[+] Tunnel hostname (from env): $TUNNEL_HOST"
  fi
  "$CLOUDFLARED_BIN" tunnel --no-autoupdate run --token "$TUNNEL_TOKEN" > /tmp/cloudflared.log 2>&1 &
  CLOUDFLARED_PID=$!
  echo "[+] cloudflared (named) pid $CLOUDFLARED_PID"
elif [ -x "$CLOUDFLARED_BIN" ]; then
  echo "[+] Starting cloudflared quick tunnel (trycloudflare.com)..."
  "$CLOUDFLARED_BIN" tunnel --no-autoupdate --url "http://127.0.0.1:${PORT}" > /tmp/cloudflared.log 2>&1 &
  CLOUDFLARED_PID=$!
  echo "[+] cloudflared (quick) pid $CLOUDFLARED_PID — waiting for hostname..."
  for i in $(seq 1 30); do
    if grep -qi "trycloudflare.com" /tmp/cloudflared.log 2>/dev/null; then
      _TH=$(grep -oiE "https?://[a-z0-9-]+\.trycloudflare\.com" /tmp/cloudflared.log | head -1 | sed -E 's|https?://||I; s|/.*||')
      if [ -n "$_TH" ]; then
        printf '%s' "$_TH" > "$TUNNEL_FILE"
        chmod 600 "$TUNNEL_FILE" 2>/dev/null || true
        echo "[+] Quick tunnel ready: $_TH"
        # Also log it so the panel can read it without waiting for the file
        python3 -c "import app.db as _db; _db.log_event('Tunnel ready: $_TH', kind='tunnel')" 2>/dev/null || true
        break
      fi
    fi
    if ! kill -0 "$CLOUDFLARED_PID" 2>/dev/null; then
      echo "[!] cloudflared exited early — check /tmp/cloudflared.log"
      cat /tmp/cloudflared.log 2>/dev/null | tail -20
      break
    fi
    sleep 1
  done
  if [ ! -s "$TUNNEL_FILE" ]; then
    echo "[!] Quick tunnel hostname not found within 30s — continuing without it (configs still work via other hosts)."
  fi
else
  echo "[ ] cloudflared not found — tunnel disabled (image without it still works)"
fi

# ── Supervision: if either process dies, take the container down so that
#    Railway restarts it cleanly.
term() {
  echo "[+] Shutting down..."
  kill -TERM "$API_PID" 2>/dev/null
  kill -TERM "$NGINX_PID" 2>/dev/null
  kill -TERM "$CLOUDFLARED_PID" 2>/dev/null
  wait
  exit 0
}
trap term SIGTERM SIGINT

echo "[+] Starting nginx on :${PORT}"
nginx -g 'daemon off;' &
NGINX_PID=$!

while true; do
  if ! kill -0 "$API_PID" 2>/dev/null; then
    echo "[!] Control plane exited — stopping container."
    kill -TERM "$NGINX_PID" 2>/dev/null
    kill -TERM "$CLOUDFLARED_PID" 2>/dev/null
    exit 1
  fi
  if ! kill -0 "$NGINX_PID" 2>/dev/null; then
    echo "[!] nginx exited — stopping container."
    kill -TERM "$API_PID" 2>/dev/null
    kill -TERM "$CLOUDFLARED_PID" 2>/dev/null
    exit 1
  fi
  # Tunnel is best-effort: if it dies, try to restart it once, but don't
  # kill the whole container — the other hosts still serve.
  if [ -n "$CLOUDFLARED_PID" ] && ! kill -0 "$CLOUDFLARED_PID" 2>/dev/null; then
    echo "[!] cloudflared died — attempting restart in 5s (other hosts still work)"
    sleep 5
    if [ -n "${TUNNEL_TOKEN:-}" ]; then
      "$CLOUDFLARED_BIN" tunnel --no-autoupdate run --token "$TUNNEL_TOKEN" > /tmp/cloudflared.log 2>&1 &
    else
      "$CLOUDFLARED_BIN" tunnel --no-autoupdate --url "http://127.0.0.1:${PORT}" > /tmp/cloudflared.log 2>&1 &
    fi
    CLOUDFLARED_PID=$!
    echo "[+] cloudflared restarted pid $CLOUDFLARED_PID"
  fi
  sleep 5
done
