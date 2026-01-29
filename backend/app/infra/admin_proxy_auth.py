from __future__ import annotations

import hmac
import time
from dataclasses import dataclass

PROXY_AUTH_HEADER_SECRET = "X-Proxy-Auth-Secret"
PROXY_AUTH_HEADER_MFA = "X-Auth-MFA"
PROXY_AUTH_HEADER_USER = "X-Admin-User"
PROXY_AUTH_HEADER_EMAIL = "X-Admin-Email"
PROXY_AUTH_HEADER_ROLES = "X-Admin-Roles"

PROXY_E2E_SIGNATURE_HEADER = "X-E2E-Proxy-Signature"
PROXY_E2E_TIMESTAMP_HEADER = "X-E2E-Proxy-Timestamp"
PROXY_E2E_ADMIN_USER_HEADER = "X-E2E-Admin-User"
PROXY_E2E_ADMIN_EMAIL_HEADER = "X-E2E-Admin-Email"
PROXY_E2E_ADMIN_ROLES_HEADER = "X-E2E-Admin-Roles"


@dataclass(frozen=True)
class E2EProxySignature:
    signature: str
    timestamp: str


def build_e2e_signature_payload(
    *,
    user: str,
    email: str,
    roles: str,
    timestamp: str,
    mfa: str,
) -> bytes:
    normalized = "\n".join([user, email, roles, timestamp, mfa])
    return normalized.encode("utf-8")


def sign_e2e_proxy_payload(
    *,
    secret: str,
    user: str,
    email: str,
    roles: str,
    timestamp: str,
    mfa: str,
) -> E2EProxySignature:
    payload = build_e2e_signature_payload(
        user=user,
        email=email,
        roles=roles,
        timestamp=timestamp,
        mfa=mfa,
    )
    signature = hmac.new(secret.encode("utf-8"), payload, "sha256").hexdigest()
    return E2EProxySignature(signature=signature, timestamp=timestamp)


def build_e2e_proxy_headers(
    *,
    proxy_secret: str,
    e2e_secret: str,
    user: str,
    email: str,
    roles: str,
    mfa_verified: bool = True,
    timestamp: int | None = None,
) -> dict[str, str]:
    if not proxy_secret:
        raise ValueError("proxy_secret is required")
    if not e2e_secret:
        raise ValueError("e2e_secret is required")
    if not user:
        raise ValueError("user is required")
    if not email:
        raise ValueError("email is required")
    if not roles:
        raise ValueError("roles is required")
    mfa_value = "true" if mfa_verified else "false"
    timestamp_value = str(int(time.time() if timestamp is None else timestamp))
    signature = sign_e2e_proxy_payload(
        secret=e2e_secret,
        user=user,
        email=email,
        roles=roles,
        timestamp=timestamp_value,
        mfa=mfa_value,
    )
    return {
        PROXY_AUTH_HEADER_SECRET: proxy_secret,
        PROXY_AUTH_HEADER_MFA: mfa_value,
        PROXY_E2E_ADMIN_USER_HEADER: user,
        PROXY_E2E_ADMIN_EMAIL_HEADER: email,
        PROXY_E2E_ADMIN_ROLES_HEADER: roles,
        PROXY_E2E_TIMESTAMP_HEADER: signature.timestamp,
        PROXY_E2E_SIGNATURE_HEADER: signature.signature,
    }


def build_proxy_headers(
    *,
    proxy_secret: str,
    user: str,
    email: str,
    roles: str,
    mfa_verified: bool = True,
) -> dict[str, str]:
    if not proxy_secret:
        raise ValueError("proxy_secret is required")
    if not user:
        raise ValueError("user is required")
    if not email:
        raise ValueError("email is required")
    if not roles:
        raise ValueError("roles is required")
    return {
        PROXY_AUTH_HEADER_SECRET: proxy_secret,
        PROXY_AUTH_HEADER_MFA: "true" if mfa_verified else "false",
        PROXY_AUTH_HEADER_USER: user,
        PROXY_AUTH_HEADER_EMAIL: email,
        PROXY_AUTH_HEADER_ROLES: roles,
    }
