# Stripe Data Map

**Document Owner:** Security/Compliance Team
**Last Reviewed:** 2026-01-26
**Review Cadence:** Quarterly
**Compliance Frameworks:** SOC 2 Type II, ISO 27001, GDPR Article 30

---

## 1. Overview

This document provides a comprehensive mapping of all personal and business data transmitted to Stripe as part of our payment processing integration. This data map supports compliance with GDPR Article 30 (Records of Processing Activities), SOC 2 CC6.1 (Logical Access Controls), and ISO 27001 A.8.2 (Information Classification).

---

## 2. Integration Architecture

### 2.1 Data Flow Summary

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   Application   │────▶│  Stripe SDK     │────▶│  Stripe API     │
│   (Backend)     │     │  (Server-side)  │     │  (PCI DSS L1)   │
└─────────────────┘     └─────────────────┘     └─────────────────┘
         │                                               │
         │                                               ▼
         │                                      ┌─────────────────┐
         │◀────────────────────────────────────│  Stripe Hosted  │
         │           Webhooks                   │  Checkout Page  │
         │                                      └─────────────────┘
                                                        │
                                                        ▼
                                               ┌─────────────────┐
                                               │   Cardholder    │
                                               │   (End User)    │
                                               └─────────────────┘
```

### 2.2 Integration Points

| Component | File Location | Purpose |
|-----------|--------------|---------|
| Stripe Client | `backend/app/infra/stripe_client.py` | API wrapper with circuit breaker |
| Stripe Functions | `backend/app/infra/stripe.py` | Checkout session creation |
| Payment Routes | `backend/app/api/routes_payments.py` | Webhook handling, deposit checkout |
| Billing Routes | `backend/app/api/routes_billing.py` | Subscription checkout, billing portal |
| Settings | `backend/app/settings.py` | Configuration (lines 205-217) |

---

## 3. Data Categories Transmitted to Stripe

### 3.1 Personal Data

| Data Element | Category | Legal Basis | Source Code Reference | Retention at Stripe |
|--------------|----------|-------------|----------------------|---------------------|
| Customer Email | Contact Info | Contract Performance | `stripe_client.py:66` (`customer_email` parameter) | Per Stripe retention policy |
| Stripe Customer ID | Identifier | Contract Performance | `billing_service.py:66` (stored locally, created by Stripe) | Account lifetime |

### 3.2 Business/Transaction Data

| Data Element | Category | Legal Basis | Source Code Reference | Purpose |
|--------------|----------|-------------|----------------------|---------|
| `org_id` | Internal Identifier | Contract Performance | `routes_billing.py:116` | Multi-tenant isolation |
| `plan_id` | Subscription Tier | Contract Performance | `routes_billing.py:116` | Subscription management |
| `booking_id` | Transaction Reference | Contract Performance | `routes_payments.py:807` | Deposit tracking |
| `invoice_id` | Transaction Reference | Contract Performance | `routes_payments.py:895` | Invoice payment tracking |
| `invoice_number` | Business Reference | Contract Performance | `routes_payments.py:895` | Customer-facing reference |
| Amount (cents) | Financial | Contract Performance | `stripe_client.py:30-67` | Payment amount |
| Currency | Financial | Contract Performance | `stripe_client.py:36` | Transaction currency |
| Product Name | Business | Contract Performance | `stripe_client.py:38` | Line item description |

### 3.3 Data NOT Transmitted (Confirmed)

| Data Element | Status | Verification |
|--------------|--------|--------------|
| **Raw Card Numbers (PAN)** | NOT HANDLED | Stripe Checkout handles all card input |
| **CVV/CVC** | NOT HANDLED | Never enters our systems |
| **Card Expiration** | NOT HANDLED | Stripe Checkout handles |
| **Cardholder Name** | NOT DIRECTLY | Only via Stripe Checkout (if collected) |
| **Billing Address** | NOT DIRECTLY | Only via Stripe Checkout (if collected) |
| **Bank Account Numbers** | NOT HANDLED | N/A for current integration |

**PCI DSS Scope Confirmation:** This application uses Stripe Checkout Sessions exclusively, which means:
- All card data is collected on Stripe-hosted pages
- Card data never transits or is stored on our infrastructure
- We operate under SAQ-A eligibility (lowest PCI scope)

---

## 4. Metadata Schema

### 4.1 Checkout Session Metadata

**Deposit Checkout** (`routes_payments.py:807`):
```json
{
  "booking_id": "<uuid>"
}
```

**Invoice Checkout** (`routes_payments.py:895-896`):
```json
{
  "invoice_id": "<uuid>",
  "invoice_number": "<string>"
}
```

**Subscription Checkout** (`routes_billing.py:116`):
```json
{
  "org_id": "<uuid>",
  "plan_id": "<string>"
}
```

### 4.2 Payment Intent Metadata

Same as checkout session metadata, propagated via `payment_intent_data.metadata` parameter.

---

## 5. Data Received from Stripe (Webhooks)

### 5.1 Webhook Events Processed

| Event Type | Data Received | Local Storage |
|------------|---------------|---------------|
| `checkout.session.completed` | Session ID, Payment Intent ID, Payment Status | `StripeEvent` table |
| `checkout.session.expired` | Session ID | `StripeEvent` table |
| `payment_intent.succeeded` | Payment Intent ID, Amount | `StripeEvent`, `Payment` tables |
| `payment_intent.payment_failed` | Payment Intent ID, Failure Reason | `StripeEvent`, `Payment` tables |
| `customer.subscription.*` | Subscription ID, Customer ID, Status, Period End | `OrganizationBilling` table |
| `charge.refunded` | Charge ID, Amount Refunded | `Payment` table |
| `charge.dispute.created` | Dispute ID, Charge ID, Reason | `Dispute` table |
| `charge.dispute.closed` | Dispute ID, Status, Resolution | `Dispute` table |
| `invoice.finalized` | Invoice details | `Invoice` status update |
| `invoice.payment_succeeded` | Payment Intent ID | `Invoice`, `Payment` tables |
| `invoice.payment_failed` | Payment Intent ID, Failure Reason | `Invoice`, `Payment` tables |

### 5.2 Stripe Identifiers Stored Locally

| Identifier | Table | Column | Purpose |
|------------|-------|--------|---------|
| Stripe Customer ID | `organization_billing` | `stripe_customer_id` | Customer reference |
| Stripe Subscription ID | `organization_billing` | `stripe_subscription_id` | Subscription reference |
| Stripe Checkout Session ID | `bookings` | `stripe_checkout_session_id` | Session tracking |
| Stripe Payment Intent ID | `bookings` | `stripe_payment_intent_id` | Payment tracking |
| Stripe Event ID | `stripe_events` | `event_id` | Idempotency |
| Stripe Event ID | `stripe_processed_events` | `event_id` | Deduplication |

---

## 6. Data Minimization Verification

### 6.1 Checklist

- [x] Only essential identifiers sent (booking_id, invoice_id, org_id, plan_id)
- [x] No personally identifiable information beyond optional email
- [x] No card data handled directly
- [x] No sensitive personal data (health, biometric, etc.)
- [x] No special category data under GDPR Article 9
- [x] Metadata limited to transaction correlation

### 6.2 Code Audit Points

| File | Line(s) | Verification |
|------|---------|--------------|
| `stripe_client.py` | 30-67 | Checkout session payload - only amount, currency, URLs, metadata |
| `stripe_client.py` | 69-107 | Subscription checkout - only price, metadata, customer ID |
| `routes_payments.py` | 807, 895 | Metadata construction - only IDs |
| `routes_billing.py` | 116 | Billing metadata - only org_id, plan_id |

---

## 7. Cross-Border Transfers

### 7.1 Data Transfer Assessment

| Aspect | Status |
|--------|--------|
| Stripe Entity | Stripe, Inc. (US) or Stripe Payments Europe, Ltd. (IE) |
| Transfer Mechanism | Standard Contractual Clauses (SCCs) via Stripe DPA |
| Adequacy Decision | EU-US Data Privacy Framework (if applicable) |
| GDPR Chapter V Compliance | Verified via Stripe DPA |

### 7.2 Data Residency

Stripe processes data in accordance with their [Data Processing Agreement](https://stripe.com/legal/dpa), which includes:
- EU data residency options for eligible accounts
- Standard Contractual Clauses for international transfers
- Binding Corporate Rules (Stripe internal)

---

## 8. Audit Trail

### 8.1 Version History

| Date | Version | Author | Changes |
|------|---------|--------|---------|
| 2026-01-26 | 1.0 | Security Team | Initial data map creation |

### 8.2 Review Log

| Review Date | Reviewer | Findings | Actions |
|-------------|----------|----------|---------|
| 2026-01-26 | Security Team | Initial review | Documented all data flows |

---

## 9. Related Documents

- [Stripe DPA Verification](./stripe_dpa.md)
- [Stripe API Key Management](./stripe_keys.md)
- [Stripe Webhook Security](./stripe_webhooks.md)
- [Stripe Quarterly Review](./stripe_review.md)
- [Payment Webhook Runbook](../runbooks/payment-webhook-failing.md)
