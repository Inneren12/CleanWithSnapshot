from __future__ import annotations

import hashlib
import json
from typing import Any


def _stable_extra_value(value: Any) -> str:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return str(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def make_stripe_idempotency_key(
    purpose: str,
    *,
    booking_id: str | None = None,
    amount_cents: int | None = None,
    currency: str | None = None,
    org_id: str | None = None,
    extra: dict | None = None,
) -> str:
    """Generate a deterministic idempotency key for a Stripe mutation.

    The key is stable across retries of the same logical operation—the same
    inputs always produce the same key—so Stripe de-duplicates the request and
    returns the original response.

    Format: ``<prefix8>-<sha256hex32>``

    The prefix is the first 8 characters of *purpose* (underscores replaced
    with hyphens) for readability in Stripe's dashboard logs.  The 32-char hex
    digest ensures global uniqueness while keeping the total key length well
    within Stripe's 255-character limit.

    Args:
        purpose: Short name of the operation, e.g. ``"deposit_checkout"``.
        booking_id: Booking UUID string, when applicable.
        amount_cents: Integer amount in the smallest currency unit.
        currency: ISO 4217 currency code (normalised to lower-case internally).
        org_id: Organisation UUID string, when applicable.
        extra: Additional key→value pairs included in the hash.  Keys are
            sorted for stability so insertion order does not matter.

    Returns:
        Idempotency key string safe for use with the Stripe API (≤ 255 chars).
    """
    parts: list[str] = [purpose]
    if booking_id is not None:
        parts.append(f"b:{booking_id}")
    if amount_cents is not None:
        parts.append(f"a:{amount_cents}")
    if currency is not None:
        parts.append(f"c:{currency.lower()}")
    if org_id is not None:
        parts.append(f"o:{org_id}")
    if extra:
        for k in sorted(extra.keys()):
            parts.append(f"x:{k}:{_stable_extra_value(extra[k])}")

    raw = "|".join(parts)
    digest = hashlib.sha256(raw.encode()).hexdigest()[:32]
    # Build a readable prefix: up to 8 chars, underscores→hyphens, trailing
    # hyphens stripped so the separator `-` below is unambiguous.
    prefix = purpose[:8].replace("_", "-").rstrip("-")
    return f"{prefix}-{digest}"
