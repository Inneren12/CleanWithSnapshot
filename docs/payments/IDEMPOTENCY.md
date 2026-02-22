# Stripe Idempotency Keys

## Purpose

Every Stripe mutation (session create, portal create, etc.) now carries a
deterministic `Idempotency-Key` header.  This prevents duplicate charges and
zombie sessions when callers retry a request—Stripe returns the original response
for any subsequent call that carries the same key within 24 hours.

## Helper

```python
from app.infra.stripe_idempotency import make_stripe_idempotency_key

key = make_stripe_idempotency_key(
    "deposit_checkout",
    booking_id=booking_id,
    amount_cents=deposit_cents,
    currency="cad",
)
```

**Signature**

```python
def make_stripe_idempotency_key(
    purpose: str,
    *,
    booking_id: str | None = None,
    amount_cents: int | None = None,
    currency: str | None = None,
    org_id: str | None = None,
    extra: dict | None = None,
) -> str: ...
```

**Format:** `<prefix8>-<sha256hex32>`

- `prefix8` — first 8 characters of `purpose` with underscores replaced by
  hyphens (readable in the Stripe dashboard).
- `sha256hex32` — first 32 hex characters of `SHA-256(canonical_input)`.

Total length is always ≤ 255 characters (Stripe's hard limit).

**Canonicalisation rules (order matters):**

| Field         | Format in hash input       |
|---------------|----------------------------|
| purpose       | `<purpose>`                |
| booking_id    | `b:<booking_id>`           |
| amount_cents  | `a:<amount_cents>`         |
| currency      | `c:<currency.lower()>`     |
| org_id        | `o:<org_id>`               |
| extra keys    | `x:<key>:<value>` (sorted) |

Fields are joined with `|`.  Absent (None) fields are omitted, so the key is
always stable and minimal.

## Mutation inventory

| Call site | Purpose string | Correlation fields |
|---|---|---|
| `routes_bookings.py` — booking deposit (Phase 1) | `deposit_checkout` | `booking_id`, `amount_cents`, `currency` |
| `routes_payments.py` — `/v1/payments/deposit/checkout` | `deposit_checkout` | `booking_id`, `amount_cents`, `currency` |
| `routes_payments.py` — `/v1/payments/invoice/checkout` | `invoice_checkout` | `amount_cents`, `currency`, `extra.invoice_id` |
| `routes_billing.py` — `/v1/billing/checkout` | `sub_checkout` | `org_id`, `extra.plan_id` |
| `routes_billing.py` — `/v1/billing/portal` | `portal` | `org_id`, `extra.customer_id` |
| `routes_public.py` — public invoice pay page | `pub_inv_checkout` | `amount_cents`, `currency`, `extra.invoice_id` |

`verify_webhook` and `Session.expire` (cancel) are read / compensating
operations and are excluded from the idempotency-key requirement, though
`cancel_checkout_session` accepts an optional `idempotency_key` parameter for
callers that need it.

## Booking deposit: anti-duplicate checkout creation

The `/v1/payments/deposit/checkout` endpoint (`routes_payments.py`) performs
a two-step defence against duplicate Stripe sessions:

1. **DB guard** — if `booking.stripe_checkout_session_id` is already set and
   `deposit_status` is `"pending"` or `"paid"`, the endpoint retrieves the
   existing Stripe session via `retrieve_checkout_session` and returns its URL
   without calling `create_checkout_session` again.

2. **Idempotency-Key guard** — if the DB guard is not triggered (e.g., first
   request) or the retrieve fails (expired session), `create_checkout_session`
   is called with the deterministic `deposit_checkout` key.  Stripe will return
   the same session object for any retry within 24 hours.

The booking creation route (`routes_bookings.py`, Phase 1) uses the same
`deposit_checkout` key computed from the pre-generated `pending_booking_id`, so
network retries during initial booking creation are also safe.

## Key stability guarantee

Same logical operation → same key → Stripe de-duplicates:

```
deposit_checkout|b:<booking_id>|a:<amount_cents>|c:<currency>
```

The key does **not** include timestamps, random nonces, or request IDs, which
guarantees cross-process and cross-restart stability for the full 24-hour Stripe
idempotency window.

## Out of scope (Epic 2 / PR-02)

- Outbox / event-driven reconciliation for crash-between-Stripe-and-DB scenarios.
- Cross-request replay safety beyond the 24-hour Stripe window.
- Per-request idempotency tokens surfaced to API consumers.

See `docs/payments/TRANSACTION_BOUNDARIES.md` for the two-phase booking pattern
that this feature builds on.
