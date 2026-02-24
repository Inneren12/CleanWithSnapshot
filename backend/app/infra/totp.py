import base64
import hashlib
import hmac
import secrets
import time
import urllib.parse
from datetime import datetime, timezone


TIME_STEP_SECONDS = 30
DIGITS = 6


def generate_totp_secret(length: int = 20) -> str:
    raw = secrets.token_bytes(length)
    return base64.b32encode(raw).decode("utf-8").rstrip("=")


def _decode_secret(secret_base32: str) -> bytes:
    padded = secret_base32.upper()
    missing_padding = len(padded) % 8
    if missing_padding:
        padded += "=" * (8 - missing_padding)
    return base64.b32decode(padded, casefold=True)


def _hotp(secret: bytes, counter: int) -> str:
    counter_bytes = counter.to_bytes(8, "big")
    digest = hmac.new(secret, counter_bytes, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    truncated = digest[offset : offset + 4]
    code_int = int.from_bytes(truncated, "big") & 0x7FFFFFFF
    code = code_int % (10**DIGITS)
    return f"{code:0{DIGITS}d}"


def generate_totp_code(secret_base32: str, *, for_time: datetime | None = None) -> str:
    secret = _decode_secret(secret_base32)
    timestamp = int((for_time or datetime.now(timezone.utc)).timestamp())
    counter = timestamp // TIME_STEP_SECONDS
    return _hotp(secret, counter)


def generate_backup_codes(count: int = 10, length: int = 10) -> list[str]:
    codes = []
    alphabet = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"  # Exclude similar chars
    for _ in range(count):
        codes.append("".join(secrets.choice(alphabet) for _ in range(length)))
    return codes


def verify_totp_code(secret_base32: str, code: str, *, window: int = 1, now: datetime | None = None) -> int | None:
    """Returns the time counter if valid, None otherwise."""
    if not code or len(code) != DIGITS or not code.isdigit():
        return None
    try:
        secret = _decode_secret(secret_base32)
    except Exception:  # noqa: BLE001
        return None
    timestamp = int((now or datetime.now(timezone.utc)).timestamp())
    current_counter = timestamp // TIME_STEP_SECONDS
    for offset in range(-window, window + 1):
        counter = current_counter + offset
        candidate = _hotp(secret, counter)
        if hmac.compare_digest(candidate, code):
            return counter
    return None


def build_otpauth_uri(label: str, secret_base32: str, *, issuer: str | None = None) -> str:
    params = {"secret": secret_base32, "period": str(TIME_STEP_SECONDS), "digits": str(DIGITS)}
    if issuer:
        params["issuer"] = issuer
    encoded_label = urllib.parse.quote(label)
    query = urllib.parse.urlencode(params)
    return f"otpauth://totp/{encoded_label}?{query}"
