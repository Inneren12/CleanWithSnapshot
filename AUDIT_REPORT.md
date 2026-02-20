# Enterprise Readiness Audit Report — CleanWithSnapshot

**Auditor:** Jules (Staff+ Production Readiness Auditor)
**Date:** 2025-02-23

---

## A) Verdict

**Maturity Classification:** **Early Production** (Security-Critical Blockers Present)

**Go/No-Go Decision:**
- **Pilot Production:** **NO-GO** (due to P0 Frontend Auth & CSP risks)
- **Standard Production:** **NO-GO**
- **Enterprise Production:** **NO-GO**

**Summary:**
The backend is highly mature, featuring advanced tenant isolation, structured PII-redacted logging, and robust authentication patterns (MFA, Proxy Auth). However, the **frontend is dangerously insecure**, relying on plaintext credential storage in `localStorage` and lacking a Content Security Policy (CSP). This combination makes the application highly vulnerable to XSS and credential theft. The system cannot safely handle real user data until these specific frontend issues are resolved.

---

## B) Blockers to ship (P0 only)

1.  **[Security] Plaintext Admin Credentials in LocalStorage**
    -   **Evidence:** `web/app/admin/page.tsx` (lines 405-406): `window.localStorage.setItem(ADMIN_STORAGE_PASSWORD_KEY, password);`
    -   **Why it blocks:** Any XSS vulnerability immediately exposes admin credentials to attackers. Enterprise security standards mandate HttpOnly cookies for session management.

2.  **[Security] Missing Content Security Policy (CSP)**
    -   **Evidence:** `web/middleware.ts` sets `Content-Security-Policy` with `script-src 'self' 'unsafe-inline'`. `web/next.config.mjs` has no `headers` configuration.
    -   **Why it blocks:** Allowing `'unsafe-inline'` negates the primary protection of CSP against XSS. Combined with finding #1, this is a catastrophic risk.

3.  **[Reliability] Outbox Race Condition**
    -   **Evidence:** `backend/app/domain/outbox/service.py` (`process_outbox` function) selects pending events using `limit(limit)` but **omits** `with_for_update(skip_locked=True)`.
    -   **Why it blocks:** In a production environment with multiple worker replicas (horizontal scaling), this guarantees duplicate event processing (double emails/webhooks) during bursts.

---

## C) Findings Table

| Severity | Category | Finding | Evidence Location | Impact | Status |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **P0** | Security | **Plaintext Password Storage** | `web/app/admin/page.tsx` (setItem) | Admin account takeover via XSS. | **Verified** |
| **P0** | Security | **Unsafe CSP** | `web/middleware.ts` | Allows inline script execution (XSS). | **Verified** |
| **P1** | Reliability | **Outbox Race Condition** | `backend/app/domain/outbox/service.py` | Duplicate jobs/emails in multi-worker env. | **Verified** |
| **P2** | Supply Chain | **Unsafe CI Installers** | `.github/workflows/ci.yml` (curl \| sh) | CI compromise via upstream script injection. | **Verified** |
| **P2** | Security | **Data Leakage in CI Artifacts** | `.github/workflows/e2e.yml` | Uploads `docker compose logs` which may contain env vars/secrets on startup. | **Verified** |
| **P2** | Ops | **Missing Offsite Backup Sync** | `docker-compose.yml` (archive_command) | `cp` only moves WAL to local volume; no evidence of s3 sync. | **Verified** |

---

## D) Strengths (Verified)

-   **Tenant Isolation:** `backend/app/infra/db.py` enforces RLS via `SET LOCAL app.current_org_id` on every transaction begin. `backend/app/infra/org_context.py` uses `ContextVar` for safe async propagation.
-   **Observability:** `backend/app/infra/logging.py` implements `RedactingJsonFormatter` with regex patterns to redact emails, phones, and tokens from logs automatically.
-   **Secret Management:** `backend/app/settings.py` uses `SecretStr` and `validate_prod_settings` to reject default secrets in production environments.
-   **Database Durability:** `docker-compose.yml` configures Postgres with `wal_level=replica` and `archive_mode=on`. `config/postgres/init-wal-archive.sh` safely initializes the archive directory.
-   **Authentication Architecture:** `backend/app/api/admin_auth.py` implements a robust multi-layer auth system including Proxy Auth (`X-Proxy-Auth-Secret` verification) and MFA enforcement (`X-Auth-MFA` header).
-   **CI/CD Pinning:** `.github/workflows/ci.yml` pins GitHub Actions by full SHA (e.g., `actions/checkout@34e114...`), mitigating supply chain attacks on actions.

---

## E) Unknowns / Not Verified

-   **Frontend Session Expiry:** While tokens have TTLs in backend settings, the frontend `localStorage` persistence mechanism (implied by `useEffect`) has no visible expiration logic verified in the inspected files.
-   **Offsite Backup:** The `archive_command` in `docker-compose.yml` copies files to a volume, but no sidecar container or script was found that syncs this volume to S3/GCS.
-   **DDoS Protection:** Rate limiting is present (`RedisRateLimiter`), but its effectiveness against distributed volumetric attacks (e.g., Cloudflare integration) was not verified in the repo config.
