#!/usr/bin/env python3
"""Generate E2E env vars, reusing existing backend/.env.e2e.ci if available."""
import os
import re
import secrets
import shlex
from typing import Any
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_CI_PATH = ROOT / "backend" / ".env.e2e.ci"

def parse_env_file(path: Path) -> dict:
    if not path.exists():
        return {}
    config = {}
    content = path.read_text(encoding="utf-8")
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        config[key] = value
    return config

existing_config = {}
if ENV_CI_PATH.exists():
    print(f"Reading existing {ENV_CI_PATH}...")
    existing_config = parse_env_file(ENV_CI_PATH)
else:
    print(f"{ENV_CI_PATH} not found. Will generate new secrets.")

# Default/Fallback values if not in file
admin_username = existing_config.get("ADMIN_BASIC_USERNAME", "e2e")
# If password missing, generate one
admin_password = existing_config.get("ADMIN_BASIC_PASSWORD", f"ci-{secrets.token_hex(32)}")

def get_val(key, default):
    return existing_config.get(key, default)

env_map = {
    "ADMIN_BASIC_USERNAME": get_val("ADMIN_BASIC_USERNAME", admin_username),
    "ADMIN_BASIC_PASSWORD": get_val("ADMIN_BASIC_PASSWORD", admin_password),
    "ADMIN_PROXY_AUTH_ENABLED": get_val("ADMIN_PROXY_AUTH_ENABLED", "true"),
    "ADMIN_PROXY_AUTH_REQUIRED": get_val("ADMIN_PROXY_AUTH_REQUIRED", "true"),
    "ADMIN_PROXY_AUTH_SECRET": get_val("ADMIN_PROXY_AUTH_SECRET", f"ci-proxy-{secrets.token_hex(32)}"),
    "ADMIN_PROXY_AUTH_E2E_ENABLED": get_val("ADMIN_PROXY_AUTH_E2E_ENABLED", "true"),
    "ADMIN_PROXY_AUTH_E2E_SECRET": get_val("ADMIN_PROXY_AUTH_E2E_SECRET", f"ci-e2e-{secrets.token_hex(32)}"),
    "TRUST_PROXY_HEADERS": get_val("TRUST_PROXY_HEADERS", "true"),
    "TRUSTED_PROXY_CIDRS": get_val("TRUSTED_PROXY_CIDRS", "127.0.0.1/32,::1/128,172.16.0.0/12"),
    "ENV_FILE": "backend/.env.e2e.ci",
    "POSTGRES_DB": "cleaning",
    "POSTGRES_USER": "postgres",
    "POSTGRES_PASSWORD": "postgres",
    "ADMIN_PROXY_AUTH_ROLE": "admin",
    "ADMIN_PROXY_AUTH_E2E_USER": admin_username,
    "ADMIN_PROXY_AUTH_E2E_EMAIL": f"{admin_username}@example.com",
    "ADMIN_PROXY_AUTH_E2E_ROLES": "admin",
    "ADMIN_PROXY_AUTH_MFA": "true",
}

# Write e2e_env_vars.sh
env_out = ROOT / "e2e_env_vars.sh"
def shell_export_line(key: str, value: Any) -> str:
    # Ensure values are safe for `source e2e_env_vars.sh`.
    # This avoids issues with commas/spaces/colons/slashes etc. (e.g., TRUSTED_PROXY_CIDRS).
    if value is None:
        value = ""
    return f"export {key}={shlex.quote(str(value))}"

lines = [shell_export_line(k, v) for k, v in env_map.items()]
env_out.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"Generated {env_out}")

print("Done!")
