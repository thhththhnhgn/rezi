#!/usr/bin/env python3
"""Generate environment variables file for Ultra Gaming VPN panel."""

import os
import json
import hashlib
from datetime import datetime

def generate_env_file(output_path="panel_env.txt"):
    """Generate environment variables and write to file."""
    
    # Generate cryptographic secrets
    secret_key = os.environ.get("SECRET_KEY", "")
    if not secret_key:
        secret_key = hashlib.sha256(os.urandom(64)).hexdigest()[:64]
    
    path_secret = os.environ.get("PATH_SECRET", "")
    if not path_secret:
        path_secret = hashlib.sha256(os.urandom(32)).hexdigest()[:32]
    
    admin_pass = os.environ.get("ADMIN_PASS", "")
    if not admin_pass:
        admin_pass = f"user{hashlib.sha256(os.urandom(16)).hexdigest()[:8]}"
    
    # Fixed configuration values
    admin_user = "admin"
    db_path = "/data/ultra.db"
    alt_hosts = "panelgaming-production.up.railway.app"
    locations = "all"
    
    # Build environment content in requested format
    env_content = f"""# Ultra Gaming VPN Panel — Environment Variables
# Auto-generated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
# Manual overrides can be added/edited as needed

ADMIN_USER="{admin_user}"
ADMIN_PASS="{admin_pass}"
SECRET_KEY="{secret_key}"
PATH_SECRET="{path_secret}"
DB_PATH="{db_path}"
ALT_HOSTS="{alt_hosts}"
LOCATIONS="{locations}"

# Optional: Uncomment and modify as needed
# TUNNEL_DISABLE=0
# PORT=8080
# SESSION_TTL=86400
# XRAY_LOGLEVEL=warning
# REALITY_DISABLE=0
"""
    
    # Write to file
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(env_content)
    
    print(f"✅ Environment file generated: {output_path}")
    print(f"   SECRET_KEY: {secret_key}")
    print(f"   PATH_SECRET: {path_secret}")
    print(f"   ADMIN_PASS: {admin_pass}")
    return output_path

if __name__ == "__main__":
    generate_env_file()