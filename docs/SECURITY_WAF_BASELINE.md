# Security WAF Baseline (PR-SEC-WAF-BASELINE-01)

## Purpose

Establish a **mandatory, blocking-mode** WAF baseline at Cloudflare to protect all application domains from common web attacks while preserving legitimate crawler access. This baseline **adds edge protections only** and does **not** change application logic.

## Scope

**Applies to:**
- All application domains/zones (e.g., `https://<domain>`, `https://api.<domain>`)
- Admin UI and API paths:
  - `https://<domain>/admin/*`
  - `https://api.<domain>/v1/admin/*`

**Does not change:**
- Backend application behavior or packages.
- Existing rate limiting rules (kept in place; see rate limit runbooks for tuning).

## Baseline controls

### A) OWASP managed ruleset (blocking)

Enable the **OWASP Core Ruleset (CRS)** in **WAF → Managed rules** for each application zone.

**Required rule categories (Action: Block):**
- SQL Injection (SQLi)
- Cross-Site Scripting (XSS)
- Local/Remote File Inclusion (LFI/RFI)
- Remote Code Execution (RCE)

**Sensitivity:**
- Use **default sensitivity** unless false positives are observed.

**Rationale:**
These categories cover common web attack classes and materially reduce exposure for both public and admin endpoints.

### B) Bot score filtering (sensitive paths only)

Enable **Bot Score** evaluation in Cloudflare Bot Management and add a WAF rule for **sensitive paths**. Do **not** block legitimate crawlers globally.

**Recommended rule (WAF → Custom rules):**
- **Expression (example):**
  - Path is **admin** or **auth** sensitive paths, AND
  - Bot score is low, AND
  - Request is **not** a verified bot

```
(
  (http.request.uri.path starts_with "/v1/admin/")
  or (http.request.uri.path starts_with "/admin/")
  or (http.request.uri.path starts_with "/v1/auth/")
)
and (cf.bot_management.score < 30)
and (not cf.bot_management.verified_bot)
```

**Action:**
- **Managed Challenge** (preferred) or **Block** for very low scores.

**Rationale:**
Bot score filtering is restricted to sensitive paths to avoid breaking legitimate crawlers on public routes while still protecting admin/auth surfaces.

### C) Rule mode and scope

- **Mode:** All WAF baseline rules are **blocking** (not monitor-only).
- **Scope:** Apply to **all application domains** and **all admin paths** listed above.

## Known exclusions / exceptions

1. **Stripe webhooks**
   - Paths: `/v1/payments/stripe/webhook` and legacy `/stripe/webhook`
   - **Bypass WAF and rate limiting** to avoid breaking payment delivery.
   - **Do not** apply bot fight mode to these endpoints.

2. **Verified bots**
   - Verified search engine bots are **excluded** from bot score blocking.

> Any new exceptions must be documented below with rationale and expiration.

## Tuning & rollback

### Tuning
- **False positives:**
  - Lower sensitivity or add a scoped exception rule for the specific path + signature.
  - Keep exceptions **narrowly scoped** and **time-bound** where possible.
- **Bot score noise:**
  - Adjust the score threshold (e.g., 30 → 20) or switch from **Block** to **Managed Challenge**.

### Rollback
- **Emergency rollback:**
  - Disable the OWASP managed ruleset and custom bot-score rule for affected zones.
  - Restore previous configuration from Cloudflare change history.

## Change control checklist

- [ ] OWASP CRS enabled (SQLi, XSS, LFI/RFI, RCE) in **blocking** mode.
- [ ] Bot score rule enabled for admin/auth paths only.
- [ ] Verified bots excluded from bot score blocking.
- [ ] Stripe webhook paths excluded from WAF/bot controls.
- [ ] Applied to all application domains/zones.
- [ ] Documented exceptions and tuning guidance updated here.
