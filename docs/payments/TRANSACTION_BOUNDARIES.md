# Payment Transaction Boundaries

## Rule
Never perform external I/O (Stripe HTTP calls) while a DB transaction is open.

## Booking flow (two-phase)
1. **Phase 1 (outside transaction):**
   - Pre-generate `pending_booking_id`.
   - If deposit is required, create Stripe Checkout Session using that booking id in metadata.
   - If Stripe creation fails, downgrade deposit policy and continue booking creation without deposit.
2. **Phase 2 (inside transaction):**
   - Create booking with `booking_id=pending_booking_id`.
   - If checkout session exists, attach `stripe_checkout_session_id` and `stripe_payment_intent_id`.
   - Commit.

## Compensation
If Phase 2 fails after Stripe session creation:
- Best-effort call Stripe Checkout Session expire (`cancel_checkout_session` wrapper).
- If compensation fails, log structured warning:
  - event: `stripe_session_cancel_failed`
  - include `booking_id`, `stripe_session_id`, `reason`
- Re-raise the original error (do not mask 409 slot conflicts or other handlers).

## Stripe wrapper
Use a **single** cancel/expire surface: `StripeClient.cancel_checkout_session` via
`app.infra.stripe_client.call_stripe_client_method(...)`.

## Epic 2 (not in this PR)
Outbox/idempotency and crash-safe reconciliation are intentionally deferred.

## Tests
`backend/tests/test_stripe_transaction_boundaries.py` covers:
- Happy path
- Stripe create failure + deposit downgrade
- DB failure after Stripe success + compensation
