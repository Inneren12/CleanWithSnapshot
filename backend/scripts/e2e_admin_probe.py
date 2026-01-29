#!/usr/bin/env python3
"""CI helper for signed admin proxy probes."""

import argparse
import os
import time
import urllib.request
from dataclasses import dataclass
from typing import Mapping

from app.infra.admin_proxy_auth import build_e2e_proxy_headers

@dataclass(frozen=True)
class ProbeConfig:
    proxy_secret: str
    mfa: str
    e2e_user: str
    e2e_email: str
    e2e_roles: str
    e2e_secret: str
    timestamp: str


def _env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    return value


def build_probe_config() -> ProbeConfig:
    timestamp = str(int(time.time()))
    return ProbeConfig(
        proxy_secret=_env("ADMIN_PROXY_AUTH_SECRET"),
        mfa="true",
        e2e_user=_env("ADMIN_PROXY_AUTH_E2E_USER"),
        e2e_email=_env("ADMIN_PROXY_AUTH_E2E_EMAIL"),
        e2e_roles=_env("ADMIN_PROXY_AUTH_E2E_ROLES") or "admin",
        e2e_secret=_env("ADMIN_PROXY_AUTH_E2E_SECRET"),
        timestamp=timestamp,
    )


def build_signed_headers(config: ProbeConfig) -> dict[str, str]:
    missing = [
        name
        for name, value in {
            "ADMIN_PROXY_AUTH_SECRET": config.proxy_secret,
            "ADMIN_PROXY_AUTH_E2E_USER": config.e2e_user,
            "ADMIN_PROXY_AUTH_E2E_EMAIL": config.e2e_email,
            "ADMIN_PROXY_AUTH_E2E_SECRET": config.e2e_secret,
            "ADMIN_PROXY_AUTH_E2E_ROLES": config.e2e_roles,
        }.items()
        if not value
    ]
    if missing:
        raise ValueError(f"Missing required values: {', '.join(missing)}")
    headers = build_e2e_proxy_headers(
        proxy_secret=config.proxy_secret,
        e2e_secret=config.e2e_secret,
        user=config.e2e_user,
        email=config.e2e_email,
        roles=config.e2e_roles,
        mfa_verified=config.mfa == "true",
        timestamp=int(config.timestamp),
    )
    if not isinstance(headers, dict):
        raise ValueError("Proxy headers must be a mapping")
    return headers


def _validate_config(config: ProbeConfig) -> None:
    missing = [
        name
        for name, value in {
            "ADMIN_PROXY_AUTH_SECRET": config.proxy_secret,
            "ADMIN_PROXY_AUTH_E2E_USER": config.e2e_user,
            "ADMIN_PROXY_AUTH_E2E_EMAIL": config.e2e_email,
            "ADMIN_PROXY_AUTH_E2E_SECRET": config.e2e_secret,
        }.items()
        if not value
    ]
    if missing:
        raise SystemExit(f"Missing required env vars: {', '.join(missing)}")


def probe(url: str, headers: Mapping[str, str]) -> int:
    request = urllib.request.Request(url, headers=dict(headers), method="GET")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.getcode()
    except urllib.error.HTTPError as exc:
        reason = exc.headers.get("X-Admin-Auth-Fail-Reason", "")
        print(f"Admin probe failed: status={exc.code} reason={reason}")
        return exc.code


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    args = parser.parse_args()

    config = build_probe_config()
    _validate_config(config)
    headers = build_signed_headers(config)
    status = probe(args.url, headers)
    if status != 200:
        raise SystemExit(f"Admin probe failed with status {status}")
    print("Admin probe OK")


if __name__ == "__main__":
    main()
