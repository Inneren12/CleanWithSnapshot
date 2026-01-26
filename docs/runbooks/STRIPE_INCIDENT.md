# Runbook: Stripe Incident Response (Key Compromise, Webhook Secret, Outage, Fraud/Chargebacks)

**Purpose:** Provide actionable steps for common Stripe incidents: API key leak, webhook secret compromise, Stripe outage, and fraud/chargeback spikes.

**Scope:** Payments, subscriptions, refunds, and webhook processing handled via Stripe.

**Owners:** On-call SRE (primary), Payments/Finance lead (secondary), Security lead (tertiary).

---

## Scenario 1: API Key Leak

### Detection signals
- Security alert: exposed `sk_live_` or `rk_live_` keys in logs, tickets, or SCM (secret scanner, GitHub, SIEM).
- Unexpected spikes in Stripe API calls from unknown IPs or user agents.
- Stripe dashboard shows new API keys created/used outside expected change window.
- Failed charges/refunds initiated outside expected workflows.

### Immediate actions (ordered)
1. **Containment: rotate keys immediately.**
   - Stripe Dashboard → Developers → API keys → roll live secret key.
   - Disable any compromised keys (revoke old key).
2. **Update application secrets.**
   - Update `STRIPE_SECRET_KEY` (and any region-specific keys) in secrets manager/ENV.
   - Redeploy services to pick up new key.
3. **Restrict API key usage.**
   - If using restricted keys, set minimal permissions and rotate restricted key.
   - Add IP allowlisting if supported by your infrastructure controls.
4. **Invalidate leaked data.**
   - Remove keys from logs/tickets/SCM. Force-rotate any derived credentials.
5. **Audit Stripe activity.**
   - Stripe Dashboard → Developers → API logs: identify unauthorized actions.
   - Export logs for incident evidence.

### Customer impact
- Possible unauthorized charges or refunds.
- Temporary payment downtime while keys rotate.
- Delayed payments/subscriptions if key update lags.

### Communication steps
- **Internal:** Notify security, finance, and product leadership; share timeline and key rotation status.
- **External (if impact confirmed):**
  - Send customer notice acknowledging payment disruption or unauthorized transactions.
  - Provide remediation steps (refunds/chargeback handling) and expected resolution time.

### Post-incident review
- Confirm key rotation completed and services redeployed.
- Verify no remaining secrets exposed in code or logs.
- Document scope of unauthorized Stripe actions and financial impact.
- Add prevention: secret scanning, CI checks, tighter permissions, and runbook updates.

---

## Scenario 2: Webhook Secret Compromise

### Detection signals
- Stripe webhook failures or signature verification errors spike.
- Unexpected valid webhook events from unknown sources or mismatched event types.
- Security alert: webhook signing secret exposed (logs, tickets, SCM).

### Immediate actions (ordered)
1. **Rotate webhook signing secret.**
   - Stripe Dashboard → Developers → Webhooks → select endpoint → rotate signing secret.
2. **Update application configuration.**
   - Update `STRIPE_WEBHOOK_SECRET` in secrets manager/ENV.
   - Redeploy the webhook receiver.
3. **Block suspected abuse.**
   - Apply WAF rules/rate limiting to webhook endpoint.
   - Restrict endpoint to Stripe IP ranges if possible.
4. **Reconcile missed events.**
   - Stripe Dashboard → Events: resend failed events since last known good window.
   - Run any internal reconciliation job to align subscription/payment states.
5. **Validate processing.**
   - Confirm signature verification succeeds and events are processed idempotently.

### Customer impact
- Delayed subscription updates, invoice status changes, or refunds.
- Potential for incorrect entitlements if spoofed events were processed.

### Communication steps
- **Internal:** Notify payments team and incident channel with secret rotation status.
- **External (if entitlements impacted):**
  - Inform affected customers of corrected billing/entitlement status.
  - Provide support contact and remediation timeline.

### Post-incident review
- Verify webhook secret rotation and endpoint protection.
- Audit event history for spoofed/invalid events processed.
- Add stricter validation (event type allowlist, idempotency keys, replay detection).

---

## Scenario 3: Stripe Outage or Degraded Service

### Detection signals
- Stripe Status page shows incident or degraded performance.
- Elevated payment failures (5xx/4xx from Stripe) in logs/metrics.
- Increased checkout latency or timeouts on payment API calls.
- Webhook delivery delays.

### Immediate actions (ordered)
1. **Confirm outage.**
   - Check https://status.stripe.com and internal monitoring dashboards.
2. **Protect user experience.**
   - Enable payment retry/backoff logic if configurable.
   - Present maintenance messaging on checkout when payment failures exceed threshold.
3. **Reduce risk of double charges.**
   - Ensure idempotency keys are set for all payment/charge creation requests.
4. **Queue operations.**
   - Temporarily queue non-critical actions (subscription changes, refunds) for later replay.
5. **Monitor recovery.**
   - Watch Stripe status updates and internal error rates.

### Customer impact
- Failed or delayed payments and subscriptions.
- Checkout interruptions or degraded payment experience.

### Communication steps
- **Internal:** Share Stripe status, error rates, and any mitigations.
- **External:**
  - If impact is user-facing, post status update and estimated time to retry payments.
  - Provide guidance: “We’ll retry automatically; no action needed unless your payment fails.”

### Post-incident review
- Reconcile queued operations and verify all payments settled.
- Review idempotency usage and error-handling coverage.
- Update runbook thresholds and alerting based on observed failure patterns.

---

## Scenario 4: Fraud / Chargeback Spike

### Detection signals
- Chargeback rate exceeds threshold (e.g., >1% rolling 7-day or Stripe dispute alert).
- Sudden increase in failed payments, refund requests, or disputed charges.
- Fraud tooling (Radar) flags a spike in high-risk scores.

### Immediate actions (ordered)
1. **Freeze risky activity.**
   - Enable Stripe Radar rules to block or review high-risk payments.
   - Temporarily disable new signups or limit high-risk regions if necessary.
2. **Investigate transactions.**
   - Pull recent payment/chargeback data by product, region, and acquisition channel.
   - Identify shared attributes (IP ranges, BINs, emails, user agents).
3. **Adjust payment controls.**
   - Require 3D Secure for elevated-risk transactions.
   - Enforce stronger verification (email/phone, velocity limits).
4. **Customer support readiness.**
   - Prepare support macros for chargeback inquiries and refund workflows.
5. **Notify acquirer if needed.**
   - Coordinate with Stripe support if thresholds threaten account status.

### Customer impact
- Legitimate customers may face additional verification.
- Refund/chargeback processing delays.
- Potential temporary checkout restrictions.

### Communication steps
- **Internal:** Inform finance, security, and support with new fraud controls.
- **External:**
  - Update help center/status message if verification requirements change.
  - Direct affected customers to support for expedited review.

### Post-incident review
- Analyze root cause (campaigns, integrations, fraud vectors).
- Tune Radar rules and velocity limits based on incident data.
- Update onboarding/checkout safeguards and monitoring alerts.

---

## References
- Stripe Dashboard → Developers → API keys / Webhooks
- Stripe Status: https://status.stripe.com
