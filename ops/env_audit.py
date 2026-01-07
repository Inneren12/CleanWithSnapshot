#!/usr/bin/env python3
"""
Production Environment Audit Tool

Validates environment configuration for production deployment.
Detects missing required keys, placeholder values, and unused keys.

Usage:
    python3 ops/env_audit.py --env /etc/cleaning/cleaning.env
    python3 ops/env_audit.py --env /etc/cleaning/cleaning.env --verbose
    python3 ops/env_audit.py --env /etc/cleaning/cleaning.env --check-unused

Exit codes:
    0 = OK (all MUST keys present, no placeholders)
    1 = Warnings only (optional missing, unused keys)
    2 = Errors (missing MUST keys or placeholders detected)
"""

import argparse
import re
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple


# MUST keys: Required for safe production operation
MUST_KEYS = {
    "APP_ENV": "Environment mode (must be 'prod' for production)",
    "POSTGRES_DB": "Database name for db container",
    "POSTGRES_USER": "Database user for db container",
    "POSTGRES_PASSWORD": "Database password for db container",
    "DATABASE_URL": "SQLAlchemy connection string",
    "AUTH_SECRET_KEY": "JWT signing and session tokens (enforced non-default)",
    "CLIENT_PORTAL_SECRET": "Client portal magic link signing (enforced non-default)",
    "WORKER_PORTAL_SECRET": "Worker portal magic link signing (enforced required)",
    "TRUST_PROXY_HEADERS": "Trust X-Forwarded headers behind reverse proxy",
    "STRICT_CORS": "Enable strict CORS validation",
    "CORS_ORIGINS": "Allowed CORS origins (required if STRICT_CORS=true)",
}

# Conditional MUST keys (required if certain features enabled)
CONDITIONAL_MUST = {
    "STRIPE_SECRET_KEY": ("If payments enabled", ["DEPOSITS_ENABLED"]),
    "STRIPE_WEBHOOK_SECRET": ("If payments enabled", ["DEPOSITS_ENABLED"]),
    "S3_BUCKET": ("If ORDER_STORAGE_BACKEND=s3", ["ORDER_STORAGE_BACKEND=s3"]),
    "S3_ACCESS_KEY": ("If ORDER_STORAGE_BACKEND=s3", ["ORDER_STORAGE_BACKEND=s3"]),
    "S3_SECRET_KEY": ("If ORDER_STORAGE_BACKEND=s3", ["ORDER_STORAGE_BACKEND=s3"]),
    "R2_BUCKET": ("If ORDER_STORAGE_BACKEND=r2", ["ORDER_STORAGE_BACKEND=r2", "ORDER_STORAGE_BACKEND=cloudflare_r2"]),
    "R2_ACCESS_KEY": ("If ORDER_STORAGE_BACKEND=r2", ["ORDER_STORAGE_BACKEND=r2", "ORDER_STORAGE_BACKEND=cloudflare_r2"]),
    "R2_SECRET_KEY": ("If ORDER_STORAGE_BACKEND=r2", ["ORDER_STORAGE_BACKEND=r2", "ORDER_STORAGE_BACKEND=cloudflare_r2"]),
    "TURNSTILE_SECRET_KEY": ("If CAPTCHA_MODE=turnstile", ["CAPTCHA_MODE=turnstile"]),
    "SENDGRID_API_KEY": ("If EMAIL_MODE=sendgrid", ["EMAIL_MODE=sendgrid"]),
    "SMTP_PASSWORD": ("If EMAIL_MODE=smtp", ["EMAIL_MODE=smtp"]),
    "METRICS_TOKEN": ("If METRICS_ENABLED=true", ["METRICS_ENABLED"]),
}

# SHOULD keys: Highly recommended for production
SHOULD_KEYS = {
    "PUBLIC_BASE_URL": "Base URL for public links (email, invoices)",
    "CLIENT_PORTAL_BASE_URL": "Client portal base URL",
    "REDIS_URL": "Redis for rate limiting and job queue",
    "EMAIL_MODE": "Email provider (smtp/sendgrid/off)",
    "EMAIL_FROM": "From email address",
    "ORDER_STORAGE_BACKEND": "Photo storage backend",
}

# Known placeholder values (case-insensitive partial matches)
PLACEHOLDER_PATTERNS = [
    r"change[-_]?me",
    r"replace[-_]?me",
    r"put[-_]?strong",
    r"generate[-_]?strong",
    r"example\.com",
    r"^example$",
    r"^secret$",
    r"^password$",
    r"^admin$",
    r"^test$",
    r"^changeit$",
    r"^placeholder$",
    r"^todo$",
    r"^fixme$",
    r"^xxx+$",
    r"^yyy+$",
    r"^zzz+$",
    r"__.*__",  # Double underscore wrapped (template markers)
    r"<.*>",    # Angle bracket wrapped
]

# Known weak/default secrets
KNOWN_WEAK_SECRETS = {
    "dev-auth-secret",
    "dev-client-portal-secret",
    "dev-worker-portal-secret",
    "dev-secret",
    "secret",
    "password",
    "admin",
    "changeme",
    "123456",
}


def load_env_file(path: Path) -> Dict[str, str]:
    """Load environment variables from a .env file. Returns {KEY: STATUS} (never values)."""
    if not path.exists():
        return {}

    env_vars = {}
    with path.open("r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            # Parse KEY=VALUE
            if "=" not in line:
                continue

            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()

            # Remove quotes if present
            if value and value[0] in ('"', "'") and value[-1] == value[0]:
                value = value[1:-1]

            # Store key with status indicator (SET, EMPTY, or PLACEHOLDER)
            if not value:
                env_vars[key] = "EMPTY"
            else:
                env_vars[key] = "SET"

    return env_vars


def get_env_value(path: Path, key: str) -> str:
    """Get actual value for a specific key (only used for validation, not printing)."""
    if not path.exists():
        return ""

    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue

            k, _, v = line.partition("=")
            if k.strip() == key:
                v = v.strip()
                if v and v[0] in ('"', "'") and v[-1] == v[0]:
                    v = v[1:-1]
                return v
    return ""


def is_placeholder_value(value: str) -> bool:
    """Check if a value looks like a placeholder (without revealing the value)."""
    if not value:
        return False

    value_lower = value.lower()

    # Check against known weak secrets
    if value_lower in KNOWN_WEAK_SECRETS:
        return True

    # Check against placeholder patterns
    for pattern in PLACEHOLDER_PATTERNS:
        if re.search(pattern, value_lower):
            return True

    # Check for very short secrets (likely placeholders)
    if len(value) < 8 and any(key in ["SECRET", "KEY", "PASSWORD", "TOKEN"] for key in value.upper().split("_")):
        return True

    return False


def check_conditional_requirements(env_vars: Dict[str, str], env_path: Path) -> List[Tuple[str, str]]:
    """Check conditional MUST requirements based on configuration."""
    missing = []

    for key, (reason, conditions) in CONDITIONAL_MUST.items():
        # Check if any condition is met
        condition_met = False
        for cond in conditions:
            if "=" in cond:
                # Check specific value (e.g., ORDER_STORAGE_BACKEND=s3)
                cond_key, cond_val = cond.split("=", 1)
                actual_val = get_env_value(env_path, cond_key)
                if actual_val.lower() == cond_val.lower():
                    condition_met = True
                    break
            else:
                # Check if key exists and is truthy
                if cond in env_vars and env_vars[cond] == "SET":
                    val = get_env_value(env_path, cond)
                    if val.lower() in ("true", "1", "yes"):
                        condition_met = True
                        break

        if condition_met and (key not in env_vars or env_vars[key] == "EMPTY"):
            missing.append((key, reason))

    return missing


def audit_environment(env_path: Path, check_unused: bool = False, verbose: bool = False) -> int:
    """
    Audit the environment file.

    Returns:
        0 = OK
        1 = Warnings only
        2 = Errors (missing MUST keys or placeholders)
    """
    print(f"🔍 Auditing environment: {env_path}")
    print()

    # Load environment
    env_vars = load_env_file(env_path)

    if not env_vars:
        print(f"❌ ERROR: Could not load environment from {env_path}")
        print(f"   File exists: {env_path.exists()}")
        return 2

    print(f"✓ Loaded {len(env_vars)} environment variables")
    print()

    errors = []
    warnings = []

    # Check MUST keys
    print("📋 Checking MUST keys (required for safe production)...")
    missing_must = []
    for key, desc in MUST_KEYS.items():
        if key not in env_vars:
            missing_must.append((key, desc))
        elif env_vars[key] == "EMPTY":
            missing_must.append((key, f"{desc} (EMPTY)"))
        elif verbose:
            print(f"   ✓ {key}: SET")

    if missing_must:
        print()
        print("❌ MISSING REQUIRED KEYS:")
        for key, desc in missing_must:
            print(f"   - {key}: {desc}")
            errors.append(f"Missing MUST key: {key}")
    else:
        print("   ✓ All MUST keys present")
    print()

    # Check conditional requirements
    print("📋 Checking conditional requirements...")
    conditional_missing = check_conditional_requirements(env_vars, env_path)
    if conditional_missing:
        print()
        print("❌ MISSING CONDITIONAL REQUIRED KEYS:")
        for key, reason in conditional_missing:
            print(f"   - {key}: {reason}")
            errors.append(f"Missing conditional key: {key}")
    else:
        print("   ✓ All conditional requirements met")
    print()

    # Check for placeholder values (only for secret keys)
    print("🔒 Checking for placeholder values in secrets...")
    secret_keys = [
        "POSTGRES_PASSWORD", "DATABASE_URL",
        "AUTH_SECRET_KEY", "CLIENT_PORTAL_SECRET", "WORKER_PORTAL_SECRET",
        "METRICS_TOKEN", "STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET",
        "S3_SECRET_KEY", "R2_SECRET_KEY", "SENDGRID_API_KEY", "SMTP_PASSWORD",
        "TURNSTILE_SECRET_KEY", "INVOICE_PUBLIC_TOKEN_SECRET", "EMAIL_UNSUBSCRIBE_SECRET",
        "ORDER_PHOTO_SIGNING_SECRET", "ADMIN_BASIC_PASSWORD", "OWNER_BASIC_PASSWORD",
    ]

    placeholders_found = []
    for key in secret_keys:
        if key in env_vars and env_vars[key] == "SET":
            value = get_env_value(env_path, key)
            if is_placeholder_value(value):
                placeholders_found.append(key)
                if verbose:
                    print(f"   ⚠️  {key}: PLACEHOLDER DETECTED")

    if placeholders_found:
        print()
        print("❌ PLACEHOLDER VALUES DETECTED (must be replaced with real secrets):")
        for key in placeholders_found:
            print(f"   - {key}")
            errors.append(f"Placeholder value: {key}")
    else:
        print("   ✓ No placeholder values detected in secret keys")
    print()

    # Check SHOULD keys
    print("📋 Checking SHOULD keys (highly recommended)...")
    missing_should = []
    for key, desc in SHOULD_KEYS.items():
        if key not in env_vars:
            missing_should.append((key, desc))
        elif env_vars[key] == "EMPTY":
            missing_should.append((key, f"{desc} (EMPTY)"))
        elif verbose:
            print(f"   ✓ {key}: SET")

    if missing_should:
        print()
        print("⚠️  RECOMMENDED KEYS MISSING:")
        for key, desc in missing_should:
            print(f"   - {key}: {desc}")
            warnings.append(f"Missing SHOULD key: {key}")
    else:
        print("   ✓ All SHOULD keys present")
    print()

    # Check for unused keys (optional)
    if check_unused:
        print("📋 Checking for unused keys...")
        # Load reference from backend/.env.production.example
        example_path = Path(__file__).parent.parent / "backend" / ".env.production.example"
        if example_path.exists():
            example_vars = load_env_file(example_path)
            # Also include all keys we know about
            known_keys = set(MUST_KEYS.keys()) | set(SHOULD_KEYS.keys()) | set(CONDITIONAL_MUST.keys()) | set(example_vars.keys())

            unused = [key for key in env_vars if key not in known_keys]
            if unused:
                print()
                print("⚠️  KEYS NOT FOUND IN .env.production.example:")
                for key in sorted(unused):
                    print(f"   - {key}")
                    warnings.append(f"Unused key: {key}")
            else:
                print("   ✓ No unused keys detected")
        else:
            print(f"   ⚠️  Could not find {example_path} for comparison")
        print()

    # Summary
    print("=" * 60)
    if errors:
        print(f"❌ AUDIT FAILED: {len(errors)} error(s), {len(warnings)} warning(s)")
        print()
        print("Errors:")
        for err in errors:
            print(f"  - {err}")
        if warnings:
            print()
            print("Warnings:")
            for warn in warnings:
                print(f"  - {warn}")
        return 2
    elif warnings:
        print(f"⚠️  AUDIT PASSED WITH WARNINGS: {len(warnings)} warning(s)")
        print()
        print("Warnings:")
        for warn in warnings:
            print(f"  - {warn}")
        return 1
    else:
        print("✅ AUDIT PASSED: Environment is ready for production")
        return 0


def main():
    parser = argparse.ArgumentParser(
        description="Production environment audit tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 ops/env_audit.py --env /etc/cleaning/cleaning.env
  python3 ops/env_audit.py --env /etc/cleaning/cleaning.env --verbose
  python3 ops/env_audit.py --env /etc/cleaning/cleaning.env --check-unused

Exit codes:
  0 = OK (all MUST keys present, no placeholders)
  1 = Warnings only (optional missing, unused keys)
  2 = Errors (missing MUST keys or placeholders detected)
        """
    )
    parser.add_argument(
        "--env",
        type=Path,
        default=Path("/etc/cleaning/cleaning.env"),
        help="Path to environment file (default: /etc/cleaning/cleaning.env)"
    )
    parser.add_argument(
        "--check-unused",
        action="store_true",
        help="Check for keys not in .env.production.example"
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Verbose output (show all checks)"
    )

    args = parser.parse_args()

    exit_code = audit_environment(args.env, check_unused=args.check_unused, verbose=args.verbose)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
