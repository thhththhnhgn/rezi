#!/bin/bash
# Generate random environment variables for Ultra Gaming VPN panel

SECRET_KEY=$(openssl rand -hex 32)
PATH_SECRET=$(openssl rand -hex 16)
ADMIN_PASS=$(openssl rand -base64 24)

echo "=========================================="
echo "ULTRA GAMING VPN — Environment Variables"
echo "=========================================="
echo ""
echo "Copy these into Railway → Variables → Raw Editor:"
echo ""
echo "ADMIN_PASS=${ADMIN_PASS}"
echo "SECRET_KEY=${SECRET_KEY}"
echo "PATH_SECRET=${PATH_SECRET}"
echo ""
echo "Recommended additional vars:"
echo "ADMIN_USER=admin"
echo "DB_PATH=/data/ultra.db"
echo ""
echo "Generated: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo ""
echo "=========================================="