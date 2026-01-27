# Security Rate Limits (PR-SEC-RATELIMIT-01)

## Purpose

Replace one-size-fits-all throttling with **endpoint-specific, edge-only** rate limits that protect sensitive flows without changing backend logic.

## Scope

- **Applies to:** Cloudflare edge (WAF → Rate Limiting rules + Custom rules)
- **Out of scope:** Application logic rate limiting or server middleware
- **Related docs:**
  - [Security WAF Baseline](SECURITY_WAF_BASELINE.md)
  - [Security WAF Custom Rules](SECURITY_WAF_CUSTOM_RULES.md)

## Per-endpoint limits

| Endpoint | Path match (Cloudflare expression) | Burst guard (Managed Challenge) | Sustained limit (Block) | Notes |
| --- | --- | --- | --- | --- |
| `/login` | `http.request.method eq "POST" and (http.request.uri.path in {"/login" "/v1/auth/login"})` | **3 requests / 10s / ip.src** | **5 requests / 1m / ip.src** | Covers UI and API login. Use failure-only counting (401/403) where supported. |
| `/admin/*` | `http.request.uri.path starts_with "/admin/" or http.request.uri.path starts_with "/v1/admin/"` | **10 requests / 10s / ip.src** | **30 requests / 1m / ip.src** | Keep admin allowlists in sync with Access/IdP policy. |
| `/export` | `http.request.method in {"GET" "POST"} and (http.request.uri.path eq "/export" or http.request.uri.path eq "/v1/data-rights/export-request" or http.request.uri.path eq "/v1/admin/data/export" or http.request.uri.path eq "/v1/admin/finance/taxes/export" or http.request.uri.path eq "/v1/admin/integrations/google/gcal/export_sync")` | N/A (no burst) | **1 request / 1m / ip.src** | Strict export gating for regulated data flows; update the list when new export routes are added. |
| `/webhooks/*` | `http.request.uri.path starts_with "/webhooks/"` | N/A | **Allowlist only** | Allow `ip.src in $webhook_provider_ips`; block all other traffic. |

## Rationale

- **Login (`/login`)**: Credential stuffing and password-spraying defense. Burst challenges allow short retries; sustained limits block automation.
- **Admin (`/admin/*`)**: High-impact operations and PII access; sustained rate caps prevent scraping or scripted admin actions.
- **Export (`/export`)**: Regulated data export flows must be tightly controlled to prevent data harvesting or exfiltration.
- **Webhooks (`/webhooks/*`)**: Integrity-protected ingress; only trusted providers can submit events.

## Burst vs. sustained behavior

- **Burst guard (Managed Challenge):** Short window to absorb legitimate spikes (login and admin). Challenge mode slows automation while allowing real users to pass.
- **Sustained block:** Hard ceiling per minute to stop repeated abuse. This enforces the required limits in the table above.
- **No burst for exports/webhooks:** These are intentionally strict because of regulatory and integrity risks.

## Observability

Rate-limit decisions must be **visible in Cloudflare logs** and traceable during incident response.

**Where to look:**
- **Cloudflare Firewall Events / Security Events** for rate-limit blocks or challenges.
- **Logpush / Instant Logs** with filters on `action` (e.g., `block`, `managed_challenge`) and rule metadata (rule ID/name).

**What to capture:**
- `Ray ID`, `rule_id`, `rule_name`, `action`, `clientIP`, `request.path`, `request.method`, and timestamps.

## Identifying false positives

1. **Confirm path + method:** Ensure the event matches the intended endpoint rule.
2. **Check IP reputation:** Compare against known admin or provider IP allowlists.
3. **Review volume pattern:** Legitimate spikes should be short-lived; sustained hits indicate abuse.
4. **Correlate with app logs:** Use request IDs (where present) to validate if real users were blocked.

## Tuning guidelines

- Start with the thresholds above and adjust **per endpoint**, never globally.
- If false positives occur:
  - Adjust the **burst guard** first (Managed Challenge window).
  - Temporarily add **scoped allowlists** for known-good IPs.
  - Keep changes time-bound and documented.
- Any change must update this document and the Cloudflare rule notes.

## Emergency override process

1. **Immediate mitigation:** Disable or switch the specific rule to Managed Challenge in Cloudflare.
2. **Apply temporary allowlist:** Add a scoped IP/CIDR allowlist for impacted operators or providers.
3. **Notify on-call/security:** Record the change in change control notes.
4. **Post-incident:** Restore the original rule, review logs, and adjust thresholds if needed.

