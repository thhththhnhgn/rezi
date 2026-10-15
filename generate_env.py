#!/usr/bin/env python3
"""Generate random environment variables for Ultra Gaming VPN panel."""

import secrets
import sys

def generate():
    secret_key = secrets.token_hex(32)    # 64 hex chars
    path_secret = secrets.token_hex(16)   # 32 hex chars
    admin_pass = secrets.token_urlsafe(18)# 24-char base64url

    print("=" * 50)
    print("ULTRA GAMING VPN — Environment Variables")
    print("=" * 50)
    print()
    print("Copy these into Railway → Variables → Raw Editor:")
    print()
    print(f"ADMIN_PASS={admin_pass}")
    print(f"SECRET_KEY={secret_key}")
    print(f"PATH_SECRET={path_secret}")
    print()
    print("Recommended additional vars:")
    print(f"ADMIN_USER=admin")
    print(f"DB_PATH=/data/ultra.db")
    print()
    print("Generated at:", __import__('datetime').datetime.now().isoformat())
    print()

if __name__ == "__main__":
    generate()