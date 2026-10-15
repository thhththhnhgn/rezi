# ULTRA GAMING VPN v3 — Railway image
FROM alpine:3.20

ARG XRAY_VERSION=""

# tor is only used when LOCATIONS is set. It is installed unconditionally
# because Railway builds the image before the variable is known, and an
# unused package costs disk but never runs: app/locations.py starts nothing
# unless a country is configured.
RUN apk add --no-cache \
        nginx \
        python3 \
        curl \
        bash \
        unzip \
        tzdata \
        ca-certificates \
        tor \
    && rm -rf /var/cache/apk/*

# ── Xray-core ─────────────────────────────────────────────────────────
RUN set -eux; \
    if [ -n "$XRAY_VERSION" ]; then \
        VER="$XRAY_VERSION"; \
    else \
        VER="$(curl -fsSL https://api.github.com/repos/XTLS/Xray-core/releases/latest \
              | grep '"tag_name"' | head -1 \
              | sed 's/.*"tag_name": *"\([^"]*\)".*/\1/')"; \
    fi; \
    echo "==> installing Xray ${VER}"; \
    curl -fSL "https://github.com/XTLS/Xray-core/releases/download/${VER}/Xray-linux-64.zip" \
          -o /tmp/xray.zip; \
    unzip -q /tmp/xray.zip -d /tmp/xray; \
    install -m 755 /tmp/xray/xray /usr/local/bin/xray; \
    mkdir -p /usr/local/share/xray; \
    for f in geoip.dat geosite.dat; do \
        [ -f "/tmp/xray/$f" ] && install -m 644 "/tmp/xray/$f" /usr/local/share/xray/ || true; \
    done; \
    rm -rf /tmp/xray*; \
    xray version

# ── cloudflared (Cloudflare Tunnel, optional) ───────────────────────────
# Provides an automatic extra hostname (xxx.trycloudflare.com) via a QUIC
# tunnel from the container to Cloudflare. No account needed for the quick
# tunnel; a named tunnel uses TUNNEL_TOKEN. See start.sh for runtime logic.
RUN set -eux; \
    echo "==> installing cloudflared (latest)"; \
    curl -fL "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64" \
          -o /usr/local/bin/cloudflared; \
    chmod +x /usr/local/bin/cloudflared; \
    cloudflared --version || echo "[!] cloudflared version check failed (non-fatal)"

# ── TCP/kernel tuning for gaming ──────────────────────────────────────
# These take effect at container start (start.sh) via sysctl-like settings.
# Alpine doesn't have sysctl in containers, but we can set socket options
# via /proc/sys at runtime if the kernel allows it, or via the Python
# control plane's socket tuning.
#
# Pre-create the sysctl values file for documentation and runtime apply:
RUN mkdir -p /etc/sysctl.d && \
    printf '# Gaming-optimized TCP settings\n\
# These are applied at container start when /proc/sys is writable.\n\
# On Railway containers /proc/sys is read-only, so we also set\n\
# socket options directly in the Python control plane and Xray config.\n\
net.core.rmem_max = 16777216\n\
net.core.wmem_max = 16777216\n\
net.ipv4.tcp_rmem = 4096 87380 16777216\n\
net.ipv4.tcp_wmem = 4096 65536 16777216\n\
net.ipv4.tcp_fastopen = 3\n\
net.ipv4.tcp_congestion_control = bbr\n\
net.core.default_qdisc = fq\n\
net.ipv4.tcp_slow_start_after_idle = 0\n\
net.ipv4.tcp_mtu_probing = 1\n\
net.ipv4.tcp_notsent_lowat = 16384\n\
net.core.netdev_max_backlog = 16384\n\
' > /etc/sysctl.d/99-gaming.conf

RUN mkdir -p /var/log/nginx /var/lib/nginx/tmp /run/nginx \
             /etc/nginx/snippets /etc/xray /data /usr/share/nginx/web

WORKDIR /app

# Application code
COPY app/               /app/app/
COPY nginx.conf.template /app/nginx.conf.template
COPY nginx-snippets/     /etc/nginx/snippets/
COPY start.sh            /app/start.sh

# Web assets
COPY web/                /usr/share/nginx/web/

RUN chmod +x /app/start.sh \
    && python3 -m compileall -q /app/app \
    && echo "ok" > /usr/share/nginx/web/.keep

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DB_PATH=/data/ultra.db \
    XRAY_BIN=/usr/local/bin/xray \
    XRAY_CONFIG=/etc/xray/config.json \
    XRAY_LOCATION_ASSET=/usr/local/share/xray \
    API_PORT=8888 \
    TOR_BIN=/usr/bin/tor \
    TOR_DIR=/tmp/tor \
    CLOUDFLARED_BIN=/usr/local/bin/cloudflared \
    TUNNEL_FILE=/tmp/tunnel_host \
    PORT=8080

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${PORT}/health" || exit 1

CMD ["/bin/bash", "/app/start.sh"]
