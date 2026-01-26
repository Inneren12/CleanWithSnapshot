# Stripe Data Processing Agreement (DPA) Verification

**Document Owner:** Legal/Compliance Team
**Last Reviewed:** 2026-01-26
**Review Cadence:** Annual (or upon material changes)
**Compliance Frameworks:** GDPR Articles 28-29, SOC 2, ISO 27001

---

## 1. Overview

This document verifies Stripe's status as a data processor under applicable data protection regulations and confirms the existence and adequacy of data processing agreements governing our use of Stripe services.

---

## 2. Processor Relationship Classification

### 2.1 Role Determination

| Entity | Role | Justification |
|--------|------|---------------|
| **Our Organization** | Data Controller | Determines purposes and means of processing payment data |
| **Stripe** | Data Processor | Processes payment data on our behalf per our instructions |

### 2.2 Processing Activities by Stripe

| Activity | Classification | Legal Basis |
|----------|---------------|-------------|
| Payment processing | Processor | Contract performance (GDPR Art. 6(1)(b)) |
| Fraud detection | Joint Controller* | Legitimate interest (GDPR Art. 6(1)(f)) |
| Regulatory compliance | Independent Controller* | Legal obligation (GDPR Art. 6(1)(c)) |

*Note: For certain activities (fraud prevention, AML/KYC), Stripe acts as an independent controller per their DPA terms.

---

## 3. DPA Acceptance Status

### 3.1 Stripe DPA Details

| Item | Status | Details |
|------|--------|---------|
| **DPA Location** | Online | https://stripe.com/legal/dpa |
| **Acceptance Method** | Automatic upon account creation | Stripe DPA applies automatically to all Stripe accounts |
| **DPA Version** | Current | Monitor for updates at https://stripe.com/legal |
| **Effective Date** | Upon Stripe account activation | N/A |

### 3.2 Acceptance Verification Checklist

- [x] Stripe account created and active
- [x] DPA terms reviewed and understood
- [x] DPA automatically applies to account (no separate signature required)
- [x] Internal record of DPA acceptance documented
- [ ] DPA signed copy archived (if custom terms negotiated)

### 3.3 Key DPA Provisions Verified

| Provision | GDPR Article | Stripe DPA Coverage | Verified |
|-----------|--------------|---------------------|----------|
| Processing only on instructions | Art. 28(3)(a) | Section 2 (Data Processing) | Yes |
| Confidentiality obligations | Art. 28(3)(b) | Section 6 (Confidentiality) | Yes |
| Security measures | Art. 28(3)(c) | Section 5 (Security) | Yes |
| Sub-processor requirements | Art. 28(3)(d) | Section 7 (Sub-processors) | Yes |
| Data subject rights assistance | Art. 28(3)(e) | Section 8 (Data Subject Rights) | Yes |
| Audit rights | Art. 28(3)(h) | Section 9 (Audits) | Yes |
| Deletion/return of data | Art. 28(3)(g) | Section 10 (Data Deletion) | Yes |

---

## 4. Standard Contractual Clauses (SCCs)

### 4.1 SCC Applicability

| Scenario | SCC Required | Status |
|----------|--------------|--------|
| EU/EEA to US transfers | Yes | Included in Stripe DPA |
| UK to US transfers | Yes | UK Addendum included |
| Swiss to US transfers | Yes | Swiss Addendum included |

### 4.2 SCC Module Selection

Per Stripe's DPA, the following SCC modules apply:

| Module | Description | Applicable |
|--------|-------------|------------|
| Module 1 | Controller to Controller | Yes (for fraud/compliance activities) |
| Module 2 | Controller to Processor | Yes (primary relationship) |
| Module 3 | Processor to Processor | N/A |
| Module 4 | Processor to Controller | N/A |

### 4.3 Supplementary Measures

Stripe implements supplementary technical and organizational measures including:

| Measure | Description |
|---------|-------------|
| Encryption in transit | TLS 1.2+ for all API communications |
| Encryption at rest | AES-256 encryption for stored data |
| Access controls | Role-based access, MFA enforcement |
| Data residency | EU data residency options available |
| Pseudonymization | Tokenization of card data |

---

## 5. EU-US Data Privacy Framework

### 5.1 Framework Status

| Item | Status |
|------|--------|
| Stripe certified under EU-US DPF | Verify at https://www.dataprivacyframework.gov |
| UK Extension | Verify current status |
| Swiss-US DPF | Verify current status |

### 5.2 Verification Procedure

To verify Stripe's Data Privacy Framework certification:

1. Visit https://www.dataprivacyframework.gov/s/participant-search
2. Search for "Stripe"
3. Confirm active certification status
4. Document verification date

**Last Verification:** 2026-01-26
**Certification Status:** [TO BE VERIFIED BY COMPLIANCE TEAM]

---

## 6. Sub-Processor Management

### 6.1 Sub-Processor List

Stripe maintains a list of sub-processors at: https://stripe.com/legal/service-providers

### 6.2 Sub-Processor Change Notifications

| Process | Status |
|---------|--------|
| Notification mechanism | Email to account contact |
| Objection period | Per DPA terms (typically 30 days) |
| Internal review process | Compliance team review required |

### 6.3 Sub-Processor Monitoring Checklist

- [ ] Subscribe to Stripe sub-processor notifications
- [ ] Document current sub-processor list
- [ ] Establish internal review process for changes
- [ ] Define objection criteria and escalation path

---

## 7. Security and Compliance Certifications

### 7.1 Stripe Certifications

| Certification | Status | Verification |
|---------------|--------|--------------|
| PCI DSS Level 1 | Active | https://stripe.com/docs/security |
| SOC 1 Type II | Active | Available under NDA |
| SOC 2 Type II | Active | Available under NDA |
| ISO 27001 | Active | https://stripe.com/docs/security |

### 7.2 Certification Verification

- Stripe Trust Center: https://stripe.com/trust
- Compliance reports available via Stripe Dashboard (Settings > Security)

---

## 8. Data Subject Rights Procedures

### 8.1 Rights Fulfillment Matrix

| Right | Controller Responsibility | Stripe Assistance |
|-------|--------------------------|-------------------|
| Access (Art. 15) | Primary | Transaction data export |
| Rectification (Art. 16) | Primary | Metadata correction via API |
| Erasure (Art. 17) | Primary | Customer deletion API |
| Restriction (Art. 18) | Primary | N/A |
| Portability (Art. 20) | Primary | Data export API |
| Objection (Art. 21) | Primary | N/A |

### 8.2 Stripe Customer Deletion

To request deletion of a Stripe customer record:

```bash
# Via Stripe API
curl https://api.stripe.com/v1/customers/{CUSTOMER_ID} \
  -u sk_live_xxx: \
  -X DELETE
```

**Note:** Stripe retains certain data for legal/regulatory compliance even after deletion.

---

## 9. Incident Response Coordination

### 9.1 Breach Notification

| Requirement | Stripe Commitment |
|-------------|-------------------|
| Notification timeline | Without undue delay |
| Notification method | Email to designated contact |
| Information provided | Nature of breach, categories affected, mitigation measures |

### 9.2 Internal Contacts

| Role | Contact | Responsibility |
|------|---------|----------------|
| Primary Security Contact | [TO BE FILLED] | Receive Stripe security notifications |
| DPO / Privacy Lead | [TO BE FILLED] | Data protection coordination |
| Legal Counsel | [TO BE FILLED] | Contract and regulatory matters |

---

## 10. Audit and Verification Rights

### 10.1 Audit Mechanisms

| Mechanism | Availability |
|-----------|--------------|
| SOC 2 Type II Report | Upon request (NDA required) |
| ISO 27001 Certificate | Public |
| PCI DSS AOC | Upon request |
| Penetration test summary | Upon request (NDA required) |

### 10.2 On-Site Audit

Per Stripe's DPA, on-site audits may be available under certain conditions:
- Prior written request required
- Reasonable notice period
- Subject to confidentiality requirements
- May be satisfied by third-party audit reports

---

## 11. Record Keeping

### 11.1 Required Records

| Record | Location | Retention |
|--------|----------|-----------|
| DPA acceptance evidence | Compliance document repository | Duration of relationship + 7 years |
| Sub-processor change notifications | Email archive | 3 years |
| Security incident communications | Incident management system | 7 years |
| Audit reports received | Secure document storage | 3 years |

### 11.2 Version History

| Date | Version | Author | Changes |
|------|---------|--------|---------|
| 2026-01-26 | 1.0 | Compliance Team | Initial DPA verification document |

---

## 12. Annual Review Checklist

- [ ] Verify Stripe DPA version is current
- [ ] Check Data Privacy Framework certification status
- [ ] Review sub-processor list for changes
- [ ] Request updated SOC 2 report
- [ ] Verify security certification validity
- [ ] Review any security incidents
- [ ] Update internal contacts

---

## 13. Related Documents

- [Stripe Data Map](./stripe_data_map.md)
- [Stripe API Key Management](./stripe_keys.md)
- [Stripe Webhook Security](./stripe_webhooks.md)
- [Stripe Quarterly Review](./stripe_review.md)
