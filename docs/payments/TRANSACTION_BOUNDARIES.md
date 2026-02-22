# Payment Transaction Boundaries

## Rule
**No external network I/O inside DB transactions.**

For Stripe-backed booking deposits, this means zero Stripe HTTP calls may happen while `session.begin()` / `begin_nested()` is active.

## Two-phase booking pattern
1. **Phase 1 (outside transaction)**
   - Pre-generate `pending_booking_id`.
   - If a deposit is required, call Stripe `create_checkout_session` with metadata containing `booking_id` (and `lead_id` when present).
   - If Stripe creation fails, downgrade to a non-deposit booking path and continue.

2. **Phase 2 (inside transaction)**
   - Open DB transaction.
   - Create booking row using `pending_booking_id`.
   - Attach Stripe identifiers (`stripe_checkout_session_id`, `stripe_payment_intent_id`) if Phase 1 succeeded.
   - Commit transaction.

## Compensation on Phase 2 failure
If Stripe session creation succeeded but DB write/commit fails:
- Perform best-effort compensation by expiring the checkout session via `cancel_checkout_session(session_id=...)`.
- Log structured failure details if compensation itself fails, including `booking_id`, `stripe_session_id`, and `lead_id` when available.
- Re-raise the original DB failure so endpoint behavior remains unchanged.

## Non-goals (Epic 2)
The following are intentionally out of scope for this refactor:
- Outbox/event-driven reconciliation.
- Cross-request idempotency keys and replay safety.
- Crash-recovery workflows for process death between Stripe create and DB rollback.

These are scheduled for Epic 2.

## How to verify
Run:
- `pytest backend/tests/test_stripe_transaction_boundaries.py -q`

The suite verifies:
- Happy path (Stripe create + DB commit).
- Stripe create failure fallback (booking still created, no checkout URL).
- DB failure after Stripe success triggers compensation and no persisted booking/session linkage.
- Stripe create executes outside transaction boundaries.

Verification:
- `grep -n "create_checkout_session" backend/app/api/routes_bookings.py`
- Ensure the Stripe create call appears before `async with transaction_ctx`.
