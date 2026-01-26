# Stripe Webhook Security Checklist

**Document Owner:** Security/Backend Team
**Last Reviewed:** 2026-01-26
**Review Cadence:** Quarterly
**Compliance Frameworks:** SOC 2 CC6.6, ISO 27001 A.14.1, PCI DSS 6.5

---

## 1. Overview

This document details the security controls implemented for Stripe webhook handling, including signature verification, replay protection, idempotency, and multi-tenant isolation.

---

## 2. Webhook Endpoint Configuration

### 2.1 Endpoint Inventory

| Endpoint | File | Line | Purpose |
|----------|------|------|---------|
| `/v1/payments/stripe/webhook` | `routes_payments.py` | 1169 | Primary webhook endpoint |
| `/stripe/webhook` | `routes_payments.py` | 1176 | Legacy webhook endpoint |

### 2.2 Stripe Dashboard Configuration

| Setting | Value | Notes |
|---------|-------|-------|
| Webhook URL | `https://{DOMAIN}/v1/payments/stripe/webhook` | Use HTTPS only |
| API Version | Current or Locked | Lock to specific version for stability |
| Events | See Section 2.3 | Only subscribe to needed events |

### 2.3 Subscribed Events

| Event | Purpose | Required |
|-------|---------|----------|
| `checkout.session.completed` | Confirm checkout payment | Yes |
| `checkout.session.expired` | Handle expired sessions | Yes |
| `payment_intent.succeeded` | Confirm payment success | Yes |
| `payment_intent.payment_failed` | Handle payment failures | Yes |
| `customer.subscription.created` | New subscription | Yes |
| `customer.subscription.updated` | Subscription changes | Yes |
| `customer.subscription.deleted` | Subscription cancellation | Yes |
| `charge.refunded` | Process refunds | Yes |
| `charge.dispute.created` | Handle disputes | Yes |
| `charge.dispute.closed` | Close disputes | Yes |
| `invoice.finalized` | Invoice lifecycle | Optional |
| `invoice.payment_succeeded` | Invoice payment | Optional |
| `invoice.payment_failed` | Invoice payment failure | Optional |

---

## 3. Signature Verification

### 3.1 Implementation Details

**Location:** `backend/app/infra/stripe_client.py:126-135`

```python
async def verify_webhook(self, payload: bytes, signature: str | None) -> Any:
    if not self.webhook_secret:
        raise ValueError("Stripe webhook secret not configured")
    if not signature:
        raise ValueError("Missing Stripe signature header")
    return await self._call(
        lambda: self.stripe.Webhook.construct_event(
            payload=payload, sig_header=signature, secret=self.webhook_secret
        )
    )
```

**Webhook Handler:** `backend/app/api/routes_payments.py:950-978`

### 3.2 Verification Checklist

| Control | Status | Implementation |
|---------|--------|----------------|
| Signature header required | Implemented | Line 955-957: Returns 400 if missing |
| Signature verification | Implemented | Line 963-964: Uses `Webhook.construct_event` |
| Webhook secret configured | Implemented | Line 953-954: Returns 503 if not configured |
| Raw payload used | Implemented | Line 951: `await http_request.body()` |
| Invalid signature rejected | Implemented | Line 974-978: Returns 400 on failure |

### 3.3 Signature Verification Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Webhook Request                              │
└─────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│ 1. Check webhook secret configured                                   │
│    - If not: Return 503 Service Unavailable                         │
└─────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│ 2. Check Stripe-Signature header present                            │
│    - If not: Return 400 Bad Request + metric                        │
└─────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│ 3. Verify signature using Stripe SDK                                 │
│    - Stripe.Webhook.construct_event(payload, signature, secret)     │
│    - If invalid: Return 400 Bad Request + metric                    │
└─────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│ 4. Proceed to event processing                                       │
└─────────────────────────────────────────────────────────────────────┘
```

### 3.4 Security Considerations

| Consideration | Status | Notes |
|---------------|--------|-------|
| Raw body preservation | Implemented | FastAPI provides raw bytes |
| Timing attack prevention | Stripe SDK | Handled by `hmac.compare_digest` |
| Webhook secret rotation | Supported | Stripe supports dual secrets |

---

## 4. Replay Protection

### 4.1 Implementation Details

The application implements multiple layers of replay protection:

**Layer 1: Event ID Deduplication Table**
- **Table:** `stripe_processed_events`
- **Location:** `routes_payments.py:994-1011`

```python
insert_stmt = (
    _processed_event_insert(session)
    .values(
        event_id=str(event_id),
        event_type=event_type,
        livemode=event_livemode,
        request_id=event_request_id,
    )
    .on_conflict_do_nothing(index_elements=[StripeProcessedEvent.event_id])
)
```

**Layer 2: Full Event Record**
- **Table:** `stripe_events`
- **Location:** `routes_payments.py:1038-1105`

**Layer 3: Payload Hash Verification**
- **Location:** `routes_payments.py:984, 1054-1060`

```python
payload_hash = hashlib.sha256(payload or b"").hexdigest()
# Later...
if existing.payload_hash != payload_hash:
    raise HTTPException(status_code=400, detail="Event payload mismatch")
```

### 4.2 Replay Protection Matrix

| Attack Vector | Mitigation | Location |
|---------------|------------|----------|
| Same event resent | Event ID deduplication | Line 1006-1012 |
| Same ID, different payload | Payload hash comparison | Line 1054-1060 |
| Old event replay | Stripe timestamp validation | Handled by Stripe SDK |
| Concurrent duplicate | Database unique constraint | `StripeProcessedEvent` table |

### 4.3 Deduplication Response Behavior

| Scenario | Response Code | Behavior |
|----------|---------------|----------|
| First receipt | 200 | Process event |
| Duplicate (already processed) | 200 | Return `processed: false` |
| Duplicate (processing) | 200 | Return `processed: false` |
| Same ID, wrong payload | 400 | Reject as potential attack |
| Same ID, wrong org | 400 | Reject as potential attack |

---

## 5. Idempotency

### 5.1 Implementation Details

**Event Processing States:**
- `processing`: Currently being handled
- `succeeded`: Successfully processed
- `ignored`: Processed but no action taken
- `error`: Processing failed (will be retried by Stripe)

**Location:** `routes_payments.py:1062-1078, 1107-1125`

### 5.2 Idempotency Guarantees

| Guarantee | Implementation |
|-----------|----------------|
| At-most-once processing | Event ID deduplication before processing |
| State tracking | `status` column in `stripe_events` |
| Error recovery | On error, remove from processed_events for retry |
| Consistent state | Transaction wraps entire webhook handler |

### 5.3 Idempotency Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│ 1. Insert into stripe_processed_events (ON CONFLICT DO NOTHING)     │
│    - If rowcount = 0: Event already processed, return early         │
└─────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│ 2. Check/create stripe_events record                                │
│    - If exists with succeeded/ignored: Return early                 │
│    - If exists with processing: Return early (concurrent request)   │
│    - Set status = 'processing'                                      │
└─────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│ 3. Process event                                                     │
│    - On success: Set status = 'succeeded' or 'ignored'              │
│    - On error: Set status = 'error', remove from processed_events   │
└─────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│ 4. Commit transaction                                                │
│    - Error in processing → Stripe will retry                        │
│    - Success → Event marked as processed                            │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 6. Multi-Tenant Isolation

### 6.1 Org Resolution

**Location:** `routes_payments.py:156-237`

The `_resolve_org_for_event` function determines the organization for each webhook event using:

1. **Metadata lookup:** `org_id`, `invoice_id`, `booking_id` in event metadata
2. **Customer lookup:** Stripe Customer ID → `OrganizationBilling` table
3. **Payment lookup:** Payment Intent/Charge → `Payment` table

### 6.2 Isolation Controls

| Control | Status | Implementation |
|---------|--------|----------------|
| Org verification for invoices | Implemented | Line 262-267 |
| Org verification for bookings | Implemented | Line 398-403 |
| Org verification for subscriptions | Implemented | Line 498-503 |
| Customer-org mismatch detection | Implemented | Line 203-204 |
| Cross-org event rejection | Implemented | Line 1042-1053 |

### 6.3 Security Responses

| Scenario | Response | Metric |
|----------|----------|--------|
| Org-customer mismatch | 400 | `org_resolution_conflict` |
| Booking not found | 200 | `org_resolution_booking_not_found` |
| Invoice not found | 200 | `org_resolution_invoice_not_found` |
| Org not found | 200 | `org_resolution_org_not_found` |
| Existing event, different org | 400 | Logged as `stripe_webhook_org_conflict` |

---

## 7. Error Handling and Resilience

### 7.1 Circuit Breaker

**Location:** `backend/app/infra/stripe_resilience.py`

```python
stripe_circuit = CircuitBreaker(
    name="stripe",
    failure_threshold=settings.stripe_circuit_failure_threshold,  # 5
    recovery_time=settings.stripe_circuit_recovery_seconds,       # 30
    window_seconds=settings.stripe_circuit_window_seconds,        # 60
    half_open_max_calls=settings.stripe_circuit_half_open_max_calls,  # 2
)
```

### 7.2 Response Codes

| Code | Meaning | Stripe Behavior |
|------|---------|-----------------|
| 200 | Success or ignored | No retry |
| 400 | Invalid request | No retry (permanent failure) |
| 500 | Processing error | Will retry |
| 503 | Circuit open / unavailable | Will retry |

### 7.3 Metrics

| Metric | Location | Purpose |
|--------|----------|---------|
| `record_webhook("processed")` | Line 1162 | Successful processing |
| `record_webhook("ignored")` | Line 1010, 1162 | Event ignored |
| `record_webhook("error")` | Line 975, 1122 | Processing error |
| `record_webhook_error(reason)` | Various | Error categorization |
| `record_stripe_webhook(outcome)` | Line 1166 | Overall webhook metric |

---

## 8. Logging and Audit Trail

### 8.1 Log Events

| Log Event | Level | Trigger |
|-----------|-------|---------|
| `stripe_webhook_invalid` | Warning | Invalid signature |
| `stripe_webhook_duplicate` | Info | Duplicate event |
| `stripe_webhook_processed` | Info | Successful processing |
| `stripe_webhook_ignored` | Info | Event ignored |
| `stripe_webhook_error` | Exception | Processing error |
| `stripe_webhook_org_mismatch` | Warning | Org resolution conflict |
| `stripe_webhook_org_conflict` | Warning | Cross-org event |
| `stripe_webhook_replayed_mismatch` | Warning | Payload mismatch |

### 8.2 Log Fields

All webhook logs include:
- `event_id`: Stripe event identifier
- `event_type`: Event type (e.g., `checkout.session.completed`)
- `org_id`: Resolved organization (if applicable)
- `reason`: Additional context for ignored/error events

---

## 9. Verification Checklist

### 9.1 Security Controls

- [x] Webhook secret stored securely (environment variable)
- [x] Signature verification implemented
- [x] Invalid signatures rejected with 400
- [x] Missing signatures rejected with 400
- [x] Raw payload used for verification (not parsed)
- [x] Replay protection via event ID deduplication
- [x] Payload hash verification for same-ID attacks
- [x] Multi-tenant isolation enforced
- [x] Cross-org events rejected
- [x] Idempotent processing
- [x] Error handling returns appropriate codes for Stripe retry logic
- [x] Circuit breaker prevents cascade failures
- [x] Comprehensive logging and metrics

### 9.2 Configuration Verification

Run this checklist before production deployment:

- [ ] `STRIPE_WEBHOOK_SECRET` environment variable set
- [ ] Webhook endpoint URL registered in Stripe Dashboard
- [ ] Only required events subscribed (see Section 2.3)
- [ ] HTTPS enforced for webhook endpoint
- [ ] Webhook endpoint accessible from Stripe IPs
- [ ] Test webhook with Stripe CLI before going live

### 9.3 Testing with Stripe CLI

```bash
# Install Stripe CLI
brew install stripe/stripe-cli/stripe

# Login
stripe login

# Forward webhooks to local endpoint
stripe listen --forward-to localhost:8000/v1/payments/stripe/webhook

# Trigger test event
stripe trigger checkout.session.completed
```

---

## 10. Incident Response

### 10.1 Webhook Failure Indicators

| Indicator | Source | Action |
|-----------|--------|--------|
| High `webhook_error` rate | Metrics | Check logs, verify secret |
| Stripe Dashboard failures | Stripe | Review failed events |
| Missing payment updates | Business | Check webhook connectivity |
| Circuit breaker open | Metrics | Check Stripe API status |

### 10.2 Runbook Reference

See [Payment Webhook Failing Runbook](../runbooks/payment-webhook-failing.md) for operational procedures.

### 10.3 Common Issues

| Issue | Cause | Resolution |
|-------|-------|------------|
| All webhooks failing | Secret mismatch | Verify `STRIPE_WEBHOOK_SECRET` |
| Intermittent failures | Clock drift | Ensure NTP sync |
| 503 responses | Circuit open | Check Stripe status, wait for recovery |
| Events missing | Endpoint unreachable | Check firewall, TLS config |

---

## 11. Version History

| Date | Version | Author | Changes |
|------|---------|--------|---------|
| 2026-01-26 | 1.0 | Security Team | Initial webhook security checklist |

---

## 12. Related Documents

- [Stripe Data Map](./stripe_data_map.md)
- [Stripe DPA Verification](./stripe_dpa.md)
- [Stripe API Key Management](./stripe_keys.md)
- [Stripe Quarterly Review](./stripe_review.md)
- [Payment Webhook Runbook](../runbooks/payment-webhook-failing.md)
