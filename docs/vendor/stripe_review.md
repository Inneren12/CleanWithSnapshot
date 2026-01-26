# Stripe Vendor Compliance Review Cadence

**Document Owner:** Compliance/Security Team
**Last Reviewed:** 2026-01-26
**Review Cadence:** Quarterly
**Compliance Frameworks:** SOC 2 CC3.2, ISO 27001 A.15.2, GDPR Article 28

---

## 1. Overview

This document defines the quarterly review process for Stripe vendor compliance, ensuring ongoing adherence to security, privacy, and regulatory requirements.

---

## 2. Review Schedule

### 2.1 Quarterly Review Calendar

| Quarter | Review Period | Due Date | Focus Areas |
|---------|--------------|----------|-------------|
| Q1 | Jan-Mar | April 15 | Annual DPA review, SOC 2 report |
| Q2 | Apr-Jun | July 15 | Key rotation verification, access review |
| Q3 | Jul-Sep | October 15 | Data map accuracy, sub-processor changes |
| Q4 | Oct-Dec | January 15 | Year-end compliance summary, planning |

### 2.2 Review Participants

| Role | Responsibility | Required |
|------|---------------|----------|
| Compliance Lead | Coordinate review, sign-off | Yes |
| Security Engineer | Technical verification | Yes |
| Backend Lead | Implementation verification | Yes |
| Legal Counsel | DPA/contract review | Quarterly |
| Finance | Payment reconciliation | Optional |

---

## 3. Quarterly Review Checklist

### 3.1 Data Map Review

**Reference:** [stripe_data_map.md](./stripe_data_map.md)

| Item | Check | Status | Notes |
|------|-------|--------|-------|
| 3.1.1 | Review data categories sent to Stripe | [ ] | |
| 3.1.2 | Verify no new PII fields added | [ ] | |
| 3.1.3 | Confirm no card data handled directly | [ ] | |
| 3.1.4 | Audit metadata fields in code | [ ] | |
| 3.1.5 | Verify data minimization principles | [ ] | |
| 3.1.6 | Update data map if changes found | [ ] | |

**Code Audit Points:**
```bash
# Search for Stripe API calls with new parameters
grep -r "stripe" backend/app --include="*.py" | grep -E "(metadata|customer_email|customer)"
```

### 3.2 DPA and Legal Compliance

**Reference:** [stripe_dpa.md](./stripe_dpa.md)

| Item | Check | Status | Notes |
|------|-------|--------|-------|
| 3.2.1 | Verify Stripe DPA still in effect | [ ] | |
| 3.2.2 | Check for DPA updates at stripe.com/legal | [ ] | |
| 3.2.3 | Verify Data Privacy Framework status | [ ] | |
| 3.2.4 | Review sub-processor change notifications | [ ] | |
| 3.2.5 | Check for new regulatory requirements | [ ] | |
| 3.2.6 | Verify SCCs still adequate | [ ] | |

**Verification URLs:**
- DPA: https://stripe.com/legal/dpa
- Sub-processors: https://stripe.com/legal/service-providers
- DPF Search: https://www.dataprivacyframework.gov/s/participant-search

### 3.3 API Key Management

**Reference:** [stripe_keys.md](./stripe_keys.md)

| Item | Check | Status | Notes |
|------|-------|--------|-------|
| 3.3.1 | Verify key rotation completed (90-day cycle) | [ ] | |
| 3.3.2 | Confirm no test keys in production | [ ] | |
| 3.3.3 | Review personnel with key access | [ ] | |
| 3.3.4 | Audit Stripe Dashboard access logs | [ ] | |
| 3.3.5 | Verify MFA enabled for all team members | [ ] | |
| 3.3.6 | Check for unused/stale keys | [ ] | |
| 3.3.7 | Review restricted key scope (if used) | [ ] | |

**Key Rotation Log Update:**
| Date | Key Type | Rotated By | Verified By |
|------|----------|------------|-------------|
| | | | |

### 3.4 Webhook Security

**Reference:** [stripe_webhooks.md](./stripe_webhooks.md)

| Item | Check | Status | Notes |
|------|-------|--------|-------|
| 3.4.1 | Review webhook failure metrics | [ ] | |
| 3.4.2 | Verify signature verification active | [ ] | |
| 3.4.3 | Check for replay attack attempts | [ ] | |
| 3.4.4 | Review circuit breaker incidents | [ ] | |
| 3.4.5 | Audit webhook event subscriptions | [ ] | |
| 3.4.6 | Verify endpoint HTTPS/TLS config | [ ] | |
| 3.4.7 | Test webhook with Stripe CLI | [ ] | |

**Metrics to Review:**
```bash
# Example Prometheus queries
sum(rate(stripe_webhook_total{status="error"}[7d]))
sum(rate(stripe_webhook_total{status="processed"}[7d]))
```

### 3.5 Security and Compliance Certifications

| Item | Check | Status | Notes |
|------|-------|--------|-------|
| 3.5.1 | Verify Stripe PCI DSS compliance current | [ ] | |
| 3.5.2 | Request updated SOC 2 report (if due) | [ ] | |
| 3.5.3 | Verify ISO 27001 certification current | [ ] | |
| 3.5.4 | Review Stripe security advisories | [ ] | |
| 3.5.5 | Check Stripe Trust Center for updates | [ ] | |

**Reference:** https://stripe.com/trust

### 3.6 Incident Review

| Item | Check | Status | Notes |
|------|-------|--------|-------|
| 3.6.1 | Review Stripe-related security incidents | [ ] | |
| 3.6.2 | Check Stripe status page history | [ ] | |
| 3.6.3 | Review internal webhook failure incidents | [ ] | |
| 3.6.4 | Document any payment processing issues | [ ] | |
| 3.6.5 | Update runbooks if needed | [ ] | |

**Reference:** https://status.stripe.com/

---

## 4. Annual Review Items

In addition to quarterly checks, perform these annually (Q1):

### 4.1 Contract and Legal

| Item | Check | Status | Notes |
|------|-------|--------|-------|
| 4.1.1 | Full DPA re-review | [ ] | |
| 4.1.2 | Terms of Service review | [ ] | |
| 4.1.3 | Pricing/fee structure review | [ ] | |
| 4.1.4 | Escalation contact verification | [ ] | |
| 4.1.5 | SLA verification | [ ] | |

### 4.2 Architecture Review

| Item | Check | Status | Notes |
|------|-------|--------|-------|
| 4.2.1 | Review Stripe integration architecture | [ ] | |
| 4.2.2 | Assess need for Stripe Connect/other products | [ ] | |
| 4.2.3 | Evaluate API version currency | [ ] | |
| 4.2.4 | Review error handling patterns | [ ] | |
| 4.2.5 | Assess performance and reliability | [ ] | |

### 4.3 Compliance Audit Preparation

| Item | Check | Status | Notes |
|------|-------|--------|-------|
| 4.3.1 | Gather SOC 2 evidence for auditors | [ ] | |
| 4.3.2 | Prepare data processing inventory | [ ] | |
| 4.3.3 | Document access control evidence | [ ] | |
| 4.3.4 | Compile key rotation evidence | [ ] | |
| 4.3.5 | Prepare incident response evidence | [ ] | |

---

## 5. Review Documentation

### 5.1 Review Sign-Off Template

```
STRIPE VENDOR COMPLIANCE QUARTERLY REVIEW

Review Period: Q[X] 20XX
Review Date: YYYY-MM-DD

SUMMARY OF FINDINGS:
[ ] No issues identified
[ ] Issues identified (see details below)

ISSUES IDENTIFIED:
1. [Issue description]
   - Severity: [High/Medium/Low]
   - Remediation: [Action required]
   - Due Date: [YYYY-MM-DD]

ATTESTATION:
I certify that this quarterly review has been completed in accordance with
the Stripe Vendor Compliance Review procedures.

Compliance Lead: _________________ Date: _________
Security Engineer: _______________ Date: _________
Backend Lead: ___________________ Date: _________
```

### 5.2 Review Archive Requirements

| Document | Retention | Location |
|----------|-----------|----------|
| Signed review checklist | 3 years | Compliance document repository |
| Evidence screenshots | 3 years | Compliance document repository |
| Remediation records | 3 years | Issue tracking system |
| Meeting notes | 1 year | Team documentation |

---

## 6. Remediation Process

### 6.1 Issue Severity Classification

| Severity | Definition | Response Time |
|----------|------------|---------------|
| Critical | Active security vulnerability or compliance violation | 24 hours |
| High | Potential security risk or near-term compliance impact | 7 days |
| Medium | Best practice deviation or minor compliance gap | 30 days |
| Low | Documentation or process improvement | 90 days |

### 6.2 Remediation Workflow

1. **Identify:** Document issue during review
2. **Classify:** Assign severity level
3. **Assign:** Designate responsible party
4. **Track:** Create ticket in issue tracker
5. **Remediate:** Implement fix
6. **Verify:** Confirm resolution
7. **Document:** Update review records

---

## 7. Escalation Procedures

### 7.1 Internal Escalation

| Trigger | Escalate To | Timeline |
|---------|-------------|----------|
| Critical finding | CISO/VP Engineering | Immediate |
| High finding not resolved in 7 days | Director level | Day 8 |
| Repeated findings | VP Engineering | Next review |
| Compliance deadline risk | Legal/Compliance | Immediate |

### 7.2 Stripe Escalation

| Issue | Contact Method | Reference |
|-------|----------------|-----------|
| Security concern | security@stripe.com | Stripe Security |
| Account issues | Stripe Dashboard support | Account settings |
| Technical issues | Stripe API support | developers.stripe.com |
| Legal/compliance | Stripe Legal | Contract terms |

---

## 8. Continuous Monitoring

### 8.1 Automated Checks

In addition to quarterly reviews, implement continuous monitoring:

| Check | Frequency | Alert Threshold |
|-------|-----------|-----------------|
| Webhook failure rate | Real-time | >5% error rate |
| Circuit breaker state | Real-time | Open state |
| API error rate | Hourly | >1% error rate |
| Key age | Daily | >80 days |

### 8.2 Metrics Dashboard

Recommended metrics to display:

- Webhook success/failure rates
- Payment success/failure rates
- Circuit breaker state changes
- API latency percentiles
- Key rotation status

---

## 9. Review History

### 9.1 Past Reviews

| Quarter | Date | Lead | Findings | Status |
|---------|------|------|----------|--------|
| Q1 2026 | 2026-01-26 | Security Team | Initial review | Complete |

### 9.2 Open Remediation Items

| Finding | Quarter | Severity | Owner | Due | Status |
|---------|---------|----------|-------|-----|--------|
| N/A | N/A | N/A | N/A | N/A | N/A |

---

## 10. Document Maintenance

### 10.1 Update Triggers

This document should be updated when:
- Review process changes
- New compliance requirements emerge
- Stripe product/service changes
- Organizational changes affect review participants
- Audit findings require process updates

### 10.2 Version History

| Date | Version | Author | Changes |
|------|---------|--------|---------|
| 2026-01-26 | 1.0 | Compliance Team | Initial review cadence document |

---

## 11. Related Documents

- [Stripe Data Map](./stripe_data_map.md)
- [Stripe DPA Verification](./stripe_dpa.md)
- [Stripe API Key Management](./stripe_keys.md)
- [Stripe Webhook Security](./stripe_webhooks.md)
- [Payment Webhook Runbook](../runbooks/payment-webhook-failing.md)
- [Access Review Policy](../ACCESS_REVIEW_POLICY.md)
- [Governance Audit](../GOVERNANCE_AUDIT.md)
