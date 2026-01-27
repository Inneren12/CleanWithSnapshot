# Security WAF Custom Rules for Sensitive Endpoints (PR-SEC-WAF-CUSTOM-01)

## Purpose

Define **path-scoped**, **blocking/challenge-mode** Cloudflare WAF and rate-limiting rules for the most sensitive application endpoints. These rules **augment** the baseline OWASP WAF controls and **do not** modify backend logic. See the baseline configuration in [`SECURITY_WAF_BASELINE.md`](SECURITY_WAF_BASELINE.md).

## Scope

**Sensitive endpoints covered:**
- `/admin/*` (UI) and `/v1/admin/*` (API)
- `/auth/*` and `/v1/auth/*`
- `/v1/estimate`, `/v1/slots`, `/v1/leads`, `/v1/bookings`
- `/data-rights/*` and `/v1/data-rights/*`
- `/webhooks/*`

**Out of scope (handled elsewhere):**
- Stripe webhooks (`/v1/payments/stripe/webhook`, `/stripe/webhook`) remain **excluded** from WAF/bot controls per baseline guidance.

## A) Sensitive endpoint classification

| Endpoint class | Paths | Risk profile | Why it matters |
| --- | --- | --- | --- |
| **Admin** | `/admin/*`, `/v1/admin/*` | **Auth + PII + financial** | Full operational access, privileged actions, and sensitive customer/finance data. |
| **Auth** | `/auth/*`, `/v1/auth/*` | **Auth + credential stuffing** | Primary login and session endpoints; targeted for brute force and credential reuse. |
| **Booking** | `/v1/estimate`, `/v1/slots`, `/v1/leads`, `/v1/bookings` | **Fraud + automation** | Public booking endpoints are abused for bot leads, inventory scraping, and payment fraud. |
| **Data rights** | `/data-rights/*`, `/v1/data-rights/*` | **PII + regulated exports** | GDPR/CCPA exports expose comprehensive subject data; abuse can cause privacy incidents. |
| **Webhooks** | `/webhooks/*` | **Automation + integrity** | Inbound integrations must be locked to trusted providers to prevent spoofed events. |

## B) Custom WAF rules per endpoint class

> **Notes:**
> - Expressions are Cloudflare WAF custom rule syntax.
> - **All actions are BLOCK or MANAGED CHALLENGE** (no monitor-only rules).
> - Keep all rules **path-scoped** as shown.

### 1) `/admin/*` and `/v1/admin/*`

**Rule: Block high-risk countries (if applicable)**
- **Action:** Block
- **Expression:**
  ```
  (
    http.request.uri.path starts_with "/admin/"
    or http.request.uri.path starts_with "/v1/admin/"
  )
  and (ip.geoip.country in {"RU", "KP", "IR", "SY", "BY", "CU"})
  and not (ip.src in $admin_allowlist_ips)
  ```
- **Rationale:** Reduce exposure to persistent threat traffic while honoring known admin/VPN allowlists.
- **Tuning:** Maintain the country set via change control; empty the set if admins are globally distributed.

**Rule: Stricter bot score threshold**
- **Action:** Block (or Managed Challenge during tuning)
- **Expression:**
  ```
  (
    http.request.uri.path starts_with "/admin/"
    or http.request.uri.path starts_with "/v1/admin/"
  )
  and (cf.bot_management.score < 20)
  and (not cf.bot_management.verified_bot)
  ```
- **Rationale:** Admin endpoints should not tolerate low-reputation automation.
- **Tuning:** Raise/lower threshold (e.g., 15–30) based on false positives.

**Rule: Challenge automated scanners/anomalies**
- **Action:** Managed Challenge
- **Expression:**
  ```
  (
    http.request.uri.path starts_with "/admin/"
    or http.request.uri.path starts_with "/v1/admin/"
  )
  and (
    cf.waf.score >= 40
    or cf.threat_score >= 20
  )
  ```
- **Rationale:** Challenge suspicious traffic while allowing legitimate operators to pass.
- **Tuning:** Adjust `cf.waf.score` cutoff to balance detection vs. usability.

**Rule: Admin burst guard**
- **Type:** Cloudflare Rate Limiting rule
- **Action:** Managed Challenge
- **Match:**
  ```
  http.request.uri.path starts_with "/admin/"
  or http.request.uri.path starts_with "/v1/admin/"
  ```
- **Threshold:** 10 requests per 10 seconds per `ip.src`
- **Rationale:** Allows small, legitimate bursts while gating automation.

**Rule: Admin sustained rate limit**
- **Type:** Cloudflare Rate Limiting rule
- **Action:** Block
- **Match:**
  ```
  http.request.uri.path starts_with "/admin/"
  or http.request.uri.path starts_with "/v1/admin/"
  ```
- **Threshold:** 30 requests per minute per `ip.src`
- **Rationale:** Enforces the required admin ceiling and prevents sustained scraping.

**Rule: No admin CAPTCHA bypass without MFA**
- **Action:** Block
- **Expression (example):**
  ```
  (
    http.request.uri.path starts_with "/admin/"
    or http.request.uri.path starts_with "/v1/admin/"
  )
  and (cf.bot_management.score < 30)
  and not (cf.access.authenticated and cf.access.mfa)
  ```
- **Rationale:** Admin access must require MFA; do not bypass bot challenges unless Cloudflare Access confirms MFA.
- **Tuning:** Align `cf.access.*` checks with Access policy headers or JWT claims used in production.

### 2) `/auth/*` and `/v1/auth/*`

**Rule: Credential stuffing guard (bot score)**
- **Action:** Managed Challenge
- **Expression:**
  ```
  (
    http.request.uri.path starts_with "/auth/"
    or http.request.uri.path starts_with "/v1/auth/"
  )
  and (http.request.method eq "POST")
  and (cf.bot_management.score < 30)
  and (not cf.bot_management.verified_bot)
  ```
- **Rationale:** Challenges suspicious automation without immediately blocking legitimate users.

**Rule: Block extremely low bot scores**
- **Action:** Block
- **Expression:**
  ```
  (
    http.request.uri.path starts_with "/auth/"
    or http.request.uri.path starts_with "/v1/auth/"
  )
  and (http.request.method eq "POST")
  and (cf.bot_management.score < 10)
  and (not cf.bot_management.verified_bot)
  ```
- **Rationale:** Prevents obvious bot traffic from reaching auth endpoints.

**Rule: Rate-limit auth attempts (challenge → block)**
- **Type:** Cloudflare Rate Limiting rule
- **Action:** Managed Challenge
- **Match:**
  ```
  http.request.method eq "POST"
  and (http.request.uri.path in {"/login" "/v1/auth/login"})
  ```
- **Threshold:** 3 requests per 10 seconds per `ip.src`
- **Failure-focused option (preferred where supported):** Count only **401/403** origin responses to target failed attempts.
- **Rationale:** Allows short login bursts while slowing automation.

**Rule: Sustained login block**
- **Type:** Cloudflare Rate Limiting rule
- **Action:** Block
- **Match:**
  ```
  http.request.method eq "POST"
  and (http.request.uri.path in {"/login" "/v1/auth/login"})
  ```
- **Threshold:** 5 requests per minute per `ip.src`
- **Rationale:** Enforces the required login ceiling and blocks sustained abuse.

### 3) `/data-rights/*` and `/v1/data-rights/*`

**Rule: Allow only known methods**
- **Action:** Block
- **Expression:**
  ```
  (
    http.request.uri.path starts_with "/data-rights/"
    or http.request.uri.path starts_with "/v1/data-rights/"
  )
  and not (http.request.method in {"GET", "POST"})
  ```
- **Rationale:** Data-rights endpoints only require GET/POST; other verbs are anomalous.

**Rule: Require auth indicator at edge**
- **Action:** Block
- **Expression (example):**
  ```
  (
    http.request.uri.path starts_with "/data-rights/"
    or http.request.uri.path starts_with "/v1/data-rights/"
  )
  and not (
    http.request.headers["authorization"][*] ne ""
    or http.request.headers["cookie"][*] contains "session"
  )
  ```
- **Rationale:** Data export endpoints are authenticated-only; this blocks anonymous probes.
- **Tuning:** Update cookie names or auth header checks to match the actual session/token format in production.

**Rule: Strict rate limits**
- **Type:** Cloudflare Rate Limiting rule
- **Action:** Block
- **Match (export requests):**
  ```
  http.request.method in {"GET" "POST"}
  and (
    http.request.uri.path eq "/export"
    or http.request.uri.path eq "/v1/data-rights/export-request"
    or http.request.uri.path eq "/v1/admin/data/export"
    or http.request.uri.path eq "/v1/admin/finance/taxes/export"
    or http.request.uri.path eq "/v1/admin/integrations/google/gcal/export_sync"
  )
  ```
- **Threshold:** 1 request per minute per `ip.src`
- **Rationale:** Enforces strict export limits for regulated data flows.

### 4) `/webhooks/*`

**Rule: Allowlist provider IPs only**
- **Action:** Allow
- **Expression:**
  ```
  (http.request.uri.path starts_with "/webhooks/")
  and (ip.src in $webhook_provider_ips)
  ```
- **Rationale:** Only trusted providers should be able to hit inbound webhook endpoints.

**Rule: Block all other webhook traffic**
- **Action:** Block
- **Expression:**
  ```
  (http.request.uri.path starts_with "/webhooks/")
  and not (ip.src in $webhook_provider_ips)
  ```
- **Rationale:** Enforces a default-deny posture for webhook ingress.

### 5) `/v1/estimate`, `/v1/slots`, `/v1/leads`, `/v1/bookings`

**Rule: Soft challenge on suspicious booking activity**
- **Action:** Managed Challenge
- **Expression:**
  ```
  (http.request.uri.path in {"/v1/estimate" "/v1/slots" "/v1/leads" "/v1/bookings"})
  and (http.request.method in {"GET" "POST"})
  and (
    cf.bot_management.score < 30
    or cf.waf.score >= 40
  )
  and (not cf.bot_management.verified_bot)
  ```
- **Rationale:** Uses Bot Management to gently challenge likely automation before it reaches booking endpoints.

**Rule: Booking velocity guard (CAPTCHA after N attempts)**
- **Type:** Cloudflare Rate Limiting rule
- **Action:** Managed Challenge
- **Match:**
  ```
  http.request.method eq "POST"
  and (http.request.uri.path in {"/v1/leads" "/v1/bookings"})
  ```
- **Threshold (example):** 5 requests per 10 minutes per `ip.src`
- **Rationale:** Introduces CAPTCHA after repeated booking submissions without blocking legitimate users.

**Rule: Escalation block for abusive booking velocity**
- **Type:** Cloudflare Rate Limiting rule
- **Action:** Block
- **Match:**
  ```
  http.request.method eq "POST"
  and (http.request.uri.path in {"/v1/leads" "/v1/bookings"})
  and (cf.bot_management.score < 20)
  ```
- **Threshold (example):** 20 requests per 30 minutes per `ip.src`
- **Rationale:** Escalates to block when low-score traffic repeatedly hammers booking submissions.

**Rule: Repeated identical payloads**
- **Type:** Cloudflare Rate Limiting rule (request body inspection enabled)
- **Action:** Managed Challenge
- **Match (example):**
  ```
  http.request.method eq "POST"
  and (http.request.uri.path in {"/v1/leads" "/v1/bookings"})
  ```
- **Characteristics (example):** `ip.src`, `http.request.uri.path`, and a JSON body fingerprint of `name`, `phone`, `address`, `preferred_dates`
- **Threshold (example):** 3 identical payloads per 10 minutes
- **Rationale:** Detects scripted replays or lead spam without blocking new, unique submissions.

## C) Rule mode and enforcement

- **All rules above are enforced in BLOCK or MANAGED CHALLENGE mode.**
- **No monitor-only rules** are permitted for these paths.
- Maintain a **change log** for list updates (`$admin_allowlist_ips`, `$webhook_provider_ips`) to keep rules auditable.

## D) False-positive handling

1. **Immediate relief (short-term):**
   - Switch the affected rule from **Block → Managed Challenge** (admin/auth only), or add a **temporary IP allowlist**.
2. **Root-cause tuning:**
   - Adjust bot-score thresholds or anomaly score cutoffs.
   - Narrow the rule to specific methods or subpaths (e.g., `/v1/auth/login` only).
3. **Document the exception:**
   - Record the rule name, reason, and expiration date in change control notes.

## Rollback / temporary disable

- Disable the specific rule(s) in Cloudflare **WAF → Custom rules** or **Rate limiting rules**.
- Re-enable after traffic analysis and threshold tuning.
- The baseline OWASP CRS should remain enabled unless an emergency rollback is required.

## Implementation checklist

- [ ] Create the four rule groups above in Cloudflare WAF (admin, auth, data-rights, webhooks).
- [ ] Create booking flow bot/velocity rules for `/v1/estimate`, `/v1/slots`, `/v1/leads`, `/v1/bookings`.
- [ ] Confirm all rules are **path-scoped** and in **BLOCK/CHALLENGE** mode.
- [ ] Maintain allowlists for `$admin_allowlist_ips` and `$webhook_provider_ips`.
- [ ] Verify Stripe webhook paths remain excluded per baseline guidance.
- [ ] Update tuning notes after observing production traffic patterns.
- [ ] Record per-endpoint rate limit decisions in `docs/SECURITY_RATE_LIMITS.md`.
