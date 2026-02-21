# Payment Transaction Boundaries

## Problem Statement

External HTTP calls to Stripe must **never** occur while a database transaction is
open.  Holding a DB transaction open during a network call creates two severe risks:

1. **Connection exhaustion** – the DB connection is held idle while waiting for a
   potentially slow (or hanging) Stripe response.  Under load, this drains the
   connection pool and causes cascading failures across unrelated requests.

2. **Phantom charges** – if the DB transaction rolls back *after* Stripe has
   already collected money (or reserved a payment method), the customer is charged
   but no internal record exists.  This is the "charged but not recorded" failure
   mode.

---

## Booking Deposit Checkout — Required Pattern

### Overview

The booking creation flow that involves a Stripe Checkout Session must follow a
strict two-phase protocol.

```
┌──────────────────────────────────────────────────────────────────────┐
│  Phase 1 — NO open DB transaction                                    │
│                                                                      │
│  1. Generate a deterministic booking_id (UUID) up-front.             │
│  2. Call Stripe: create_checkout_session(metadata={booking_id})      │
│     • On success: store the returned session object.                 │
│     • On failure: downgrade deposit requirement; proceed without     │
│       deposit (no transaction was ever opened, nothing to undo).     │
└──────────────────────────────────────────────────────────────────────┘
          │
          │  (Stripe call complete – no DB connection held)
          ▼
┌──────────────────────────────────────────────────────────────────────┐
│  Phase 2 — DB transaction open                                       │
│                                                                      │
│  3. BEGIN transaction                                                │
│  4. INSERT booking row (using the pre-generated booking_id).        │
│  5. If Stripe session was created: UPDATE booking with              │
│     stripe_checkout_session_id / stripe_payment_intent_id.          │
│  6. COMMIT                                                           │
└──────────────────────────────────────────────────────────────────────┘
          │
          │  SUCCESS → return 201 with checkout_url
          │
          └─── FAILURE (any exception inside Phase 2)
                    │
                    ▼
          ┌─────────────────────────────────────────┐
          │  Compensation (best-effort)              │
          │  • Call stripe.checkout.Session.expire() │
          │  • Log structured WARNING if it fails    │
          │  • Re-raise the original exception       │
          └─────────────────────────────────────────┘
```

### Code Location

| File | Responsibility |
|------|---------------|
| `backend/app/api/routes_bookings.py` | Orchestrates Phase 1 + Phase 2 + compensation |
| `backend/app/domain/bookings/service.py` | `create_booking()` – accepts pre-generated `booking_id` |
| `backend/app/infra/stripe.py` | `create_checkout_session()`, `cancel_checkout_session()` |
| `backend/app/infra/stripe_client.py` | `StripeClient.create_checkout_session()`, `StripeClient.cancel_checkout_session()` |

### Key Implementation Details

**Pre-generated `booking_id`**

A UUID is generated before any DB work begins:

```python
pending_booking_id = str(uuid.uuid4())
```

This ID is embedded in the Stripe session metadata so that webhook events can
correlate the payment back to the booking even if the booking row has not yet been
committed.

**Compensation on Phase 2 failure**

```python
except (ValueError, Exception):
    if stripe_checkout_session is not None:
        try:
            await stripe_infra.cancel_checkout_session(
                stripe_client=stripe_client,
                secret_key=settings.stripe_secret_key,
                session_id=stripe_checkout_session.id,
            )
        except Exception as cancel_exc:
            logger.warning(
                "stripe_session_cancel_failed",
                extra={"extra": {"stripe_session_id": ..., "reason": ...}},
            )
    raise
```

The cancellation is **best-effort**: if it fails, a structured `WARNING` is emitted
with enough context to allow manual reconciliation.  The original exception is
always re-raised so the API caller receives the correct error response.

**Stripe `expire` vs `cancel`**

Stripe's Checkout Sessions do not have a generic "cancel" verb.  The correct API
call is `stripe.checkout.Session.expire(session_id)`, which prevents any further
payment from being collected on that session.  Sessions already in a terminal state
(paid, expired) will return a 400 from Stripe; the compensation handler silently
ignores this (it means the session was already settled — no action needed).

---

## What Is NOT Covered Here (Epic 2)

The pattern described above is **not** idempotent across process crashes.  If the
Python process dies between Phase 1 (Stripe succeeded) and Phase 2 (DB write), the
Stripe session will remain open and eventually expire on its own (default: 24 h).

Robust idempotency via an **outbox table** or a **pending-intents reconciliation
job** is deferred to Epic 2 and is out of scope for this PR.

---

## Testing

See `backend/tests/test_stripe_transaction_boundaries.py` for the authoritative
test suite covering:

| Test | Scenario |
|------|---------|
| `test_happy_path_stripe_and_db_succeed` | Both phases succeed; booking + checkout_url returned |
| `test_stripe_fails_deposit_downgraded_booking_still_created` | Phase 1 Stripe error; deposit downgraded, booking still created without deposit |
| `test_db_fails_after_stripe_succeeds_compensation_called` | Phase 2 DB error; Stripe session expired; no booking persisted |
| `test_db_fails_stripe_cancel_also_fails_warning_logged` | Both phases fail; structured warning emitted; 409 returned |

---

## Invariants

1. **No Stripe HTTP calls inside `async with transaction_ctx`.**
2. **Every Stripe session created gets either a DB record or a best-effort `expire()`.**
3. **The `booking_id` in Stripe metadata always matches the committed DB record.**
4. **Compensation failures are logged as `stripe_session_cancel_failed` with
   `stripe_session_id` and `reason` fields for operational alerting.**
