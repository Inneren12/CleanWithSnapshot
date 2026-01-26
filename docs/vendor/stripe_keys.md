# Stripe API Key Management Checklist

**Document Owner:** Security/DevOps Team
**Last Reviewed:** 2026-01-26
**Review Cadence:** Quarterly
**Compliance Frameworks:** SOC 2 CC6.1, ISO 27001 A.9.2, PCI DSS 3.6

---

## 1. Overview

This document establishes policies and procedures for managing Stripe API keys, including key types, storage requirements, rotation schedules, and access controls.

---

## 2. Key Types and Usage

### 2.1 Key Inventory

| Key Type | Environment Variable | Purpose | Scope |
|----------|---------------------|---------|-------|
| Secret Key | `STRIPE_SECRET_KEY` | Server-side API calls | Full API access |
| Webhook Secret | `STRIPE_WEBHOOK_SECRET` | Webhook signature verification | Webhook endpoint only |

### 2.2 Key Prefixes and Identification

| Prefix | Type | Environment | Usage |
|--------|------|-------------|-------|
| `sk_test_` | Secret Key | Test/Development | Non-production testing only |
| `sk_live_` | Secret Key | Production | Live payment processing |
| `whsec_` | Webhook Secret | Both | Webhook signature verification |
| `pk_test_` | Publishable Key | Test/Development | NOT USED (Checkout Sessions) |
| `pk_live_` | Publishable Key | Production | NOT USED (Checkout Sessions) |
| `rk_test_` | Restricted Key | Test/Development | Limited scope access |
| `rk_live_` | Restricted Key | Production | Limited scope access |

### 2.3 Configuration Reference

From `backend/app/settings.py` (lines 205-206):

```python
stripe_secret_key: str | None = Field(None)
stripe_webhook_secret: str | None = Field(None)
```

---

## 3. Test vs. Live Key Policy

### 3.1 Environment Separation Matrix

| Environment | Key Type | Allowed | Enforcement |
|-------------|----------|---------|-------------|
| Local Development | `sk_test_*` | Yes | Manual verification |
| CI/CD Pipeline | `sk_test_*` | Yes | Environment variable check |
| Staging | `sk_test_*` | Yes | Environment variable check |
| Production | `sk_live_*` | Yes | Startup validation |
| Production | `sk_test_*` | **NO** | Startup validation |

### 3.2 Enforcement Controls

**Application-Level Validation:**

The application should validate key prefixes at startup in production:

```python
# Recommended validation (add to settings.py validate_prod_settings)
if self.app_env == "prod" and self.stripe_secret_key:
    if self.stripe_secret_key.startswith("sk_test_"):
        raise ValueError("Test Stripe keys are not allowed in production")
```

**Current Implementation Status:**
- [ ] Startup validation implemented
- [x] Environment variable separation in deployment
- [x] CI/CD pipeline uses test keys only

### 3.3 Test Key Safety Checklist

- [x] Test keys never committed to source control
- [x] Test keys stored in environment variables or secrets manager
- [x] Test keys do not process real payments
- [x] Separate Stripe account for testing (recommended)

---

## 4. Key Storage Requirements

### 4.1 Storage Matrix

| Storage Method | Allowed | Security Level | Use Case |
|----------------|---------|----------------|----------|
| Environment Variables | Yes | Medium | Single-server deployments |
| Secrets Manager (AWS/GCP/Azure) | Yes | High | Cloud deployments |
| HashiCorp Vault | Yes | High | Enterprise deployments |
| `.env` files | Dev Only | Low | Local development |
| Source Code | **NO** | N/A | Never allowed |
| Config Files | **NO** | N/A | Never allowed |
| Logs | **NO** | N/A | Never logged |
| Database | **NO** | N/A | Never stored |

### 4.2 Current Storage Implementation

| Key | Storage Location | Access Control |
|-----|-----------------|----------------|
| `STRIPE_SECRET_KEY` | Environment variable | Server access only |
| `STRIPE_WEBHOOK_SECRET` | Environment variable | Server access only |

### 4.3 Secrets Manager Integration (Recommended)

For production environments, use a secrets manager:

**AWS Secrets Manager:**
```bash
aws secretsmanager get-secret-value --secret-id stripe/production/secret-key
```

**HashiCorp Vault:**
```bash
vault kv get -field=secret_key secret/stripe/production
```

---

## 5. Key Rotation Policy

### 5.1 Rotation Schedule

| Key Type | Rotation Frequency | Trigger Events |
|----------|-------------------|----------------|
| Secret Key | Every 90 days | Scheduled rotation |
| Secret Key | Immediate | Suspected compromise |
| Secret Key | Immediate | Personnel departure |
| Webhook Secret | Every 90 days | Scheduled rotation |
| Webhook Secret | Immediate | Suspected compromise |

### 5.2 Rotation Procedure

#### 5.2.1 Secret Key Rotation

1. **Pre-Rotation (Day -7)**
   - [ ] Schedule maintenance window if required
   - [ ] Notify relevant teams
   - [ ] Prepare new key in Stripe Dashboard

2. **Generate New Key**
   - [ ] Log into Stripe Dashboard
   - [ ] Navigate to Developers > API Keys
   - [ ] Click "Roll key" or create new restricted key
   - [ ] Copy new key securely (one-time display)

3. **Deploy New Key**
   - [ ] Update secrets manager or environment variable
   - [ ] Deploy to staging environment
   - [ ] Verify staging functionality
   - [ ] Deploy to production
   - [ ] Verify production functionality

4. **Post-Rotation**
   - [ ] Revoke old key (after grace period if using parallel keys)
   - [ ] Update key rotation log
   - [ ] Document in audit trail

#### 5.2.2 Webhook Secret Rotation

1. **Generate New Webhook Secret**
   - [ ] Navigate to Stripe Dashboard > Webhooks
   - [ ] Select webhook endpoint
   - [ ] Click "Reveal" then "Roll secret"
   - [ ] Note: Stripe supports two secrets during transition

2. **Update Application**
   - [ ] Update `STRIPE_WEBHOOK_SECRET` environment variable
   - [ ] Deploy application changes
   - [ ] Both old and new secrets work during transition

3. **Complete Rotation**
   - [ ] Verify webhooks processing correctly
   - [ ] Remove old secret (automatic after rollover)
   - [ ] Document rotation

### 5.3 Rotation Log Template

| Date | Key Type | Reason | Performed By | Verified By |
|------|----------|--------|--------------|-------------|
| YYYY-MM-DD | Secret Key | Scheduled | [Name] | [Name] |
| YYYY-MM-DD | Webhook Secret | Scheduled | [Name] | [Name] |

---

## 6. Scope Restrictions (Restricted Keys)

### 6.1 Recommended Restricted Key Configuration

Instead of using unrestricted secret keys, create restricted keys with minimal permissions:

| Permission | Required | Justification |
|------------|----------|---------------|
| `checkout.sessions:write` | Yes | Create checkout sessions |
| `billing_portal.sessions:write` | Yes | Create billing portal sessions |
| `webhooks:read` | Yes | Verify webhook signatures |
| `customers:write` | Optional | Customer management |
| `subscriptions:read` | Optional | Subscription status |
| All other permissions | No | Minimize scope |

### 6.2 Creating a Restricted Key

1. Navigate to Stripe Dashboard > Developers > API Keys
2. Click "Create restricted key"
3. Name: `Production - Application Server`
4. Select only required permissions (see 6.1)
5. Click "Create key"

### 6.3 Current vs. Recommended Scope

| Current Implementation | Recommended |
|-----------------------|-------------|
| Unrestricted secret key | Restricted key with minimal scope |

**Action Item:** Evaluate migration to restricted keys to reduce blast radius of key compromise.

---

## 7. Access Control

### 7.1 Personnel Access Matrix

| Role | Stripe Dashboard | View Keys | Rotate Keys | Production Keys |
|------|-----------------|-----------|-------------|-----------------|
| Security Admin | Full | Yes | Yes | Yes |
| DevOps Lead | Full | Yes | Yes | Yes |
| Backend Developer | Limited | No | No | No |
| Support | Read-only | No | No | No |

### 7.2 Access Review Schedule

- **Frequency:** Quarterly
- **Scope:** All personnel with Stripe Dashboard access
- **Documentation:** Access review log maintained separately

### 7.3 Stripe Dashboard Security

| Control | Status | Notes |
|---------|--------|-------|
| MFA Required | Required | Enforce for all team members |
| SSO Integration | Recommended | SAML/OIDC if available |
| IP Allowlist | Optional | For high-security environments |
| Audit Logging | Enabled | Review monthly |

---

## 8. Incident Response

### 8.1 Key Compromise Response Procedure

**Immediate Actions (within 15 minutes):**

1. [ ] Rotate compromised key immediately in Stripe Dashboard
2. [ ] Deploy new key to production
3. [ ] Notify security team
4. [ ] Begin incident documentation

**Investigation (within 24 hours):**

1. [ ] Review Stripe Dashboard audit logs
2. [ ] Review application access logs
3. [ ] Identify scope of potential exposure
4. [ ] Check for unauthorized API calls

**Post-Incident (within 72 hours):**

1. [ ] Complete incident report
2. [ ] Identify root cause
3. [ ] Implement preventive measures
4. [ ] Update procedures if needed

### 8.2 Stripe Support Contact

For suspected account compromise:
- Email: support@stripe.com
- Dashboard: Help > Contact Support
- Priority: Mark as "Security Issue"

---

## 9. Audit and Compliance

### 9.1 Stripe Dashboard Audit Logs

Review the following in Stripe Dashboard regularly:

| Log Type | Location | Review Frequency |
|----------|----------|------------------|
| API Request Logs | Developers > Logs | Weekly |
| Team Activity | Settings > Team | Monthly |
| Key Usage | API Keys > View logs | Monthly |

### 9.2 Compliance Evidence Collection

For SOC 2 / ISO 27001 audits, maintain:

| Evidence | Retention | Format |
|----------|-----------|--------|
| Key rotation log | 3 years | Spreadsheet/Database |
| Access review records | 3 years | Signed documents |
| Incident reports | 7 years | Formal reports |
| Policy versions | Current + 2 prior | This document |

---

## 10. Checklist Summary

### 10.1 Initial Setup Checklist

- [ ] Stripe account created
- [ ] Test keys generated for development
- [ ] Live keys generated for production
- [ ] Keys stored in secrets manager (not source code)
- [ ] Webhook secret configured
- [ ] MFA enabled for Stripe Dashboard
- [ ] Team access roles configured

### 10.2 Quarterly Review Checklist

- [ ] Verify key rotation completed (90-day cycle)
- [ ] Review personnel access
- [ ] Audit API request logs
- [ ] Verify test/live key separation
- [ ] Check for unused keys (revoke if found)
- [ ] Update this document if needed

---

## 11. Version History

| Date | Version | Author | Changes |
|------|---------|--------|---------|
| 2026-01-26 | 1.0 | Security Team | Initial key management checklist |

---

## 12. Related Documents

- [Stripe Data Map](./stripe_data_map.md)
- [Stripe DPA Verification](./stripe_dpa.md)
- [Stripe Webhook Security](./stripe_webhooks.md)
- [Stripe Quarterly Review](./stripe_review.md)
