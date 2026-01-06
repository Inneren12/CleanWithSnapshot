#!/usr/bin/env python3
"""Lightweight environment audit tool.

Loads a target env file (defaults to /etc/cleaning/cleaning.env) and reports:
- Missing MUST keys
- Placeholder values for sensitive keys
- Missing recommended SHOULD keys
- Keys present in the env file but not referenced by the registry (potentially unused)

No secret values are ever printed; only key names and status are shown.
Exit codes:
    0: all good
    1: warnings only
    2: missing MUST keys or placeholder values detected
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Iterable

DEFAULT_ENV_PATH = Path("/etc/cleaning/cleaning.env")
EXAMPLE_PATH = Path("backend/.env.production.example")

# Keys that are required for a safe production deploy
MUST_KEYS: set[str] = {
    "APP_ENV",
    "DATABASE_URL",
    "POSTGRES_DB",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "AUTH_SECRET_KEY",
    "CLIENT_PORTAL_SECRET",
    "WORKER_PORTAL_SECRET",
}

# Recommended but not strictly required keys
SHOULD_KEYS: set[str] = {
    "PUBLIC_BASE_URL",
    "TRUST_PROXY_HEADERS",
    "STRICT_CORS",
    "CORS_ORIGINS",
    "CLIENT_PORTAL_BASE_URL",
    "METRICS_ENABLED",
    "METRICS_TOKEN",
    "ADMIN_BASIC_USERNAME",
    "ADMIN_BASIC_PASSWORD",
    "ADMIN_NOTIFICATION_EMAIL",
}

# Keys referenced in code but missing from the production example file
KNOWN_MISSING_FROM_EXAMPLE = {
    "ACCOUNTANT_BASIC_PASSWORD",
    "ACCOUNTANT_BASIC_USERNAME",
    "ADMIN_ACTION_RATE_LIMIT_PER_MINUTE",
    "ADMIN_BASIC_PASSWORD",
    "ADMIN_BASIC_USERNAME",
    "ADMIN_IP_ALLOWLIST_CIDRS_RAW",
    "ADMIN_MFA_REQUIRED",
    "ADMIN_MFA_REQUIRED_ROLES_RAW",
    "ADMIN_READ_ONLY",
    "BETTER_STACK_HEARTBEAT_URL",
    "CF_IMAGES_ACCOUNT_HASH",
    "CF_IMAGES_ACCOUNT_ID",
    "CF_IMAGES_API_TOKEN",
    "CF_IMAGES_DEFAULT_VARIANT",
    "CF_IMAGES_SIGNING_KEY",
    "CF_IMAGES_THUMBNAIL_VARIANT",
    "CORS_ORIGINS_RAW",
    "DISPATCHER_BASIC_PASSWORD",
    "DISPATCHER_BASIC_USERNAME",
    "DLQ_AUTO_REPLAY_ALLOW_EXPORT_MODES_RAW",
    "DLQ_AUTO_REPLAY_ALLOW_OUTBOX_KINDS_RAW",
    "DLQ_AUTO_REPLAY_ENABLED",
    "DLQ_AUTO_REPLAY_EXPORT_COOLDOWN_MINUTES",
    "DLQ_AUTO_REPLAY_EXPORT_REPLAY_LIMIT",
    "DLQ_AUTO_REPLAY_FAILURE_STREAK_LIMIT",
    "DLQ_AUTO_REPLAY_MAX_PER_ORG",
    "DLQ_AUTO_REPLAY_MIN_AGE_MINUTES",
    "DLQ_AUTO_REPLAY_OUTBOX_ATTEMPT_CEILING",
    "EMAIL_TEMP_PASSWORDS",
    "EXPORT_WEBHOOK_ALLOWED_HOSTS_RAW",
    "JOB_OUTBOX_BATCH_SIZE",
    "LEGACY_BASIC_AUTH_ENABLED",
    "OUTBOX_BASE_BACKOFF_SECONDS",
    "OUTBOX_MAX_ATTEMPTS",
    "OWNER_BASIC_PASSWORD",
    "OWNER_BASIC_USERNAME",
    "PHOTO_DOWNLOAD_REDIRECT_STATUS",
    "PHOTO_TOKEN_BIND_UA",
    "PHOTO_TOKEN_ONE_TIME",
    "PHOTO_TOKEN_SECRET",
    "PHOTO_URL_TTL_SECONDS",
    "RATE_LIMIT_FAIL_OPEN_SECONDS",
    "RATE_LIMIT_REDIS_PROBE_SECONDS",
    "S3_CIRCUIT_FAILURE_THRESHOLD",
    "S3_CIRCUIT_RECOVERY_SECONDS",
    "S3_CIRCUIT_WINDOW_SECONDS",
    "STRICT_POLICY_MODE",
    "STRIPE_CIRCUIT_HALF_OPEN_MAX_CALLS",
    "STRIPE_CIRCUIT_WINDOW_SECONDS",
    "TRUSTED_PROXY_CIDRS_RAW",
    "TRUSTED_PROXY_IPS_RAW",
    "VIEWER_BASIC_PASSWORD",
    "VIEWER_BASIC_USERNAME",
}

# Additional keys used by compose, scripts, or the web frontend
EXTRA_RUNTIME_KEYS = {
    "API_BASE_URL",
    "WEB_BASE_URL",
    "NEXT_PUBLIC_API_BASE_URL",
    "NEXT_PUBLIC_SITE_URL",
}

PLACEHOLDER_PATTERNS = (
    r"change[-_ ]?me",
    r"replace[-_ ]?me",
    r"example",
    r"^password$",
    r"^admin$",
    r"^secret$",
    r"<.*>",
    r"^dev-",
    r"^test",
)


def load_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip()
    return env


def load_example_keys() -> set[str]:
    keys: set[str] = set()
    if not EXAMPLE_PATH.exists():
        return keys
    for raw_line in EXAMPLE_PATH.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _ = line.split("=", 1)
            keys.add(key.strip())
    return keys


def is_truthy(value: str | None) -> bool:
    if value is None:
        return False
    return value.lower() not in {"", "0", "false", "off", "no"}


def has_placeholder(value: str | None) -> bool:
    if value is None:
        return False
    normalized = value.strip().lower()
    return any(re.search(pattern, normalized) for pattern in PLACEHOLDER_PATTERNS)


def resolve_known_keys() -> set[str]:
    example_keys = load_example_keys()
    known = set(example_keys)
    known.update(KNOWN_MISSING_FROM_EXAMPLE)
    known.update(MUST_KEYS)
    known.update(SHOULD_KEYS)
    known.update(EXTRA_RUNTIME_KEYS)
    return known


def audit(env: dict[str, str]) -> tuple[list[str], list[str], list[str], list[str]]:
    missing_must = [key for key in MUST_KEYS if not env.get(key)]

    placeholder_keys: list[str] = []
    for key, value in env.items():
        if has_placeholder(value):
            placeholder_keys.append(key)

    conditional_must: list[str] = []
    if is_truthy(env.get("METRICS_ENABLED", env.get("METRICS_ENABLED"))):
        if not env.get("METRICS_TOKEN"):
            conditional_must.append("METRICS_TOKEN")

    email_mode = env.get("EMAIL_MODE", "").lower()
    if email_mode == "sendgrid" and not env.get("SENDGRID_API_KEY"):
        conditional_must.append("SENDGRID_API_KEY")
    if email_mode == "smtp":
        for key in ("SMTP_HOST", "SMTP_PORT", "SMTP_USERNAME", "SMTP_PASSWORD"):
            if not env.get(key):
                conditional_must.append(key)

    if is_truthy(env.get("LEGACY_BASIC_AUTH_ENABLED")):
        pairs = [
            (env.get("OWNER_BASIC_USERNAME"), env.get("OWNER_BASIC_PASSWORD")),
            (env.get("ADMIN_BASIC_USERNAME"), env.get("ADMIN_BASIC_PASSWORD")),
            (env.get("DISPATCHER_BASIC_USERNAME"), env.get("DISPATCHER_BASIC_PASSWORD")),
            (env.get("ACCOUNTANT_BASIC_USERNAME"), env.get("ACCOUNTANT_BASIC_PASSWORD")),
            (env.get("VIEWER_BASIC_USERNAME"), env.get("VIEWER_BASIC_PASSWORD")),
        ]
        if not any(u and p for u, p in pairs):
            conditional_must.append("LEGACY_BASIC_AUTH_CREDENTIALS")

    missing_should = [key for key in SHOULD_KEYS if not env.get(key)]

    known_keys = resolve_known_keys()
    unused_keys = [key for key in env if key not in known_keys]

    missing_all = missing_must + conditional_must
    return missing_all, missing_should, placeholder_keys, unused_keys


def format_block(title: str, keys: Iterable[str]) -> str:
    entries = sorted(set(keys))
    if not entries:
        return f"{title}: none"
    joined = "\n  - " + "\n  - ".join(entries)
    return f"{title}:{joined}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit environment keys without leaking secrets")
    parser.add_argument(
        "--env",
        dest="env_path",
        default=str(DEFAULT_ENV_PATH),
        help="Path to env file (default: /etc/cleaning/cleaning.env)",
    )
    args = parser.parse_args()

    env_path = Path(args.env_path)
    env = load_env(env_path)

    missing, missing_should, placeholders, unused = audit(env)

    print(f"Env file: {env_path}")
    print(format_block("Missing MUST keys", missing))
    print(format_block("Missing SHOULD keys", missing_should))
    print(format_block("Placeholder values", placeholders))
    print(format_block("Unused keys", unused))

    if missing or placeholders:
        return 2
    if missing_should or unused:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
