# Security Bot Protection (PR-SEC-BOT-01)

## Purpose

Define **edge-only** bot protections for admin, auth, and booking flows using **Cloudflare Bot Management**, WAF custom rules, and rate limiting. These controls **do not** modify application logic and are designed to challenge suspicious automation while preserving legitimate user access.

## Cloudflare Bot Management capabilities (used here)

- **Bot score** (`cf.bot_management.score`) to rank traffic quality (lower = more likely automated).
- **Verified bot allow** (`cf.bot_management.verified_bot`) to exclude legitimate crawlers.
- **Managed Challenge / Turnstile** rendering for soft friction without hard blocks.
- **Request-aware rate limiting** with method/path/response filters for abuse patterns.

## What is protected

### Admin access (strict)

**Paths:** `/admin/*`, `/v1/admin/*`

**Controls:**
- Bot score enforcement with **Block** for very low scores.
- **Managed Challenge** on scanner/anomaly signals.
- MFA-bound bypass only: **no CAPTCHA bypass without MFA**.

**Rationale:** Admin access exposes privileged actions and sensitive data; automated scanners and low-score traffic must be denied.

### Booking flow (user-friendly)

**Paths:** `/v1/estimate`, `/v1/slots`, `/v1/leads`, `/v1/bookings`

**Controls:**
- Soft **Managed Challenge** when bot score/anomaly signals are elevated.
- **CAPTCHA after N attempts** via rate limiting on repeated booking submissions.
- **Escalation to block** only after repeated low-score abuse.
- Rate limiting for **repeated identical payloads** (request body fingerprinting).

**Rationale:** Booking endpoints are public-facing and must remain usable for real customers, so we use challenges and progressive friction before blocking.

### Auth / credential stuffing (escalation)

**Paths:** `/auth/*`, `/v1/auth/*`

**Controls:**
- **Managed Challenge** for low bot scores on login POSTs.
- **Block** for extremely low bot scores.
- Rate limiting based on **failed login responses** (401/403).
- Escalate from **challenge → block** for persistent low-score traffic.

**Rationale:** Credential stuffing is best handled with bot scoring + rate limits while keeping legitimate users in a challenge-first experience.

## What users may see

- **Admin users:** Cloudflare Managed Challenge (Turnstile) if the request looks automated. MFA is required for any bypass; without MFA, automated traffic is blocked.
- **Booking users:** A lightweight CAPTCHA after multiple submissions or if traffic looks automated; otherwise requests proceed normally.
- **Auth users:** Managed Challenge if login attempts look automated, with blocking only for repeated, low-score abuse.

## Support guidance for false positives

1. **Verify user context:** Confirm IP, region, and device fingerprints with the user.
2. **Temporary relief:** Switch the specific rule from **Block → Managed Challenge** or add a **short-lived IP allowlist**.
3. **Tuning:** Adjust bot score thresholds or rate limits in the affected rule group (admin/auth/booking).
4. **Document the exception:** Record the rule name, reason, and expiration date in change control notes.

## References

- WAF baseline: `docs/SECURITY_WAF_BASELINE.md`
- WAF custom rules: `docs/SECURITY_WAF_CUSTOM_RULES.md`
