# Enterprise Readiness Audit Report
**Date:** 2025-02-18
**Auditor:** Jules (Staff+ Production Readiness Auditor)
**Scope:** Backend, Frontend, CI/CD, Infra/Ops

## A) Verdict
**Maturity Classification:** **Early Production** (Not Enterprise-Ready)

**Go/No-Go:**
- **Pilot production:** **GO** (with P0 fixes)
- **Standard production:** **NO-GO**
- **Enterprise production:** **NO-GO**

**Blockers:** Critical security vulnerabilities in frontend authentication and missing defense-in-depth controls prevent enterprise deployment.

## B) Blockers to ship (P0 only)
- **Plaintext Password Storage in LocalStorage**: The admin frontend stores raw passwords in `localStorage` to construct Basic Auth headers. This is a critical vulnerability exposing credentials to XSS.
  - *Evidence:* `web/app/admin/lib/adminAuth.ts`: `window.localStorage.getItem(ADMIN_STORAGE_PASSWORD_KEY)`
- **Missing Content Security Policy (CSP) on Frontend**: The Next.js application serves content without a CSP, leaving it vulnerable to XSS and data injection.
  - *Evidence:* `web/next.config.mjs` is empty; no `middleware.ts` found in `web/`; `Caddyfile` only applies CSP to API docs (`@docs path ...`).
- **Unverified CI Installers**: Supply chain risk in CI pipeline executing remote scripts without checksum verification.
  - *Evidence:* `.github/workflows/ci.yml`: `curl -sSfL .../install.sh | sh` for Syft and Grype.

## C) Findings table

| Severity | Category | Evidence | Impact | Status |
| :--- | :--- | :--- | :--- | :--- |
| **P0** | Security | `web/app/admin/lib/adminAuth.ts` reads `ADMIN_STORAGE_PASSWORD_KEY` from localStorage. | XSS can steal plain-text admin credentials. | **Verified** |
| **P0** | Security | `web` project lacks `middleware.ts` and `next.config.mjs` has no headers. `Caddyfile` excludes web from CSP. | High risk of XSS/Data Exfiltration. | **Verified** |
| **P0** | Supply Chain | `.github/workflows/ci.yml`: `curl ... | sh` for Syft/Grype installers. | Compromised installer could inject malware into build env. | **Verified** |
| **P2** | Reliability | `backend/app/api/routes_orders.py`: `await file.read()` in `upload_order_photo`. | Large file uploads can exhaust server memory (DoS). | **Verified** |
| **P2** | Ops | `docker-compose.yml`: Database backup uses local volume `pg_wal_archive` but offsite sync is not verified in code. | Risk of data loss if host disk fails. | **NOT VERIFIED** |

## D) Strengths (Verified only)
- **Secret Safety**: Backend enforces `SecretStr` and fails startup on default/missing secrets in production.
  - *Evidence:* `backend/app/settings.py`: `validate_prod_config` raises `RuntimeError`.
- **Tenant Isolation**: Strong `org_id` context propagation and Postgres RLS policies.
  - *Evidence:* `backend/app/infra/db.py`: `SET LOCAL app.current_org_id ...`; `backend/alembic/versions/0044_postgres_rls_org_isolation.py`.
- **Migration Safety**: CI enforces single Alembic head and audits RLS coverage.
  - *Evidence:* `.github/workflows/ci.yml`: `alembic heads` check and `rls-audit` job.
- **Observability**: Full stack tracing (Tempo), metrics (Prometheus), and logs (Loki) configured.
  - *Evidence:* `docker-compose.yml`: Services configured with `OTEL_EXPORTER_OTLP_ENDPOINT`.
- **Background Jobs**: Resilient job runner with exception handling and metric recording.
  - *Evidence:* `backend/app/jobs/run.py`: `try...except` block updating `JobHeartbeat`.

## E) Unknowns / Not verified
- **Disaster Recovery Drills**: Backup artifacts exist (WAL archiving), but actual restore procedures and drills were not verified in execution logs.
- **Frontend Session Management**: Apart from the admin Basic Auth issue, consumer session handling (cookies vs tokens) in `web/app` was not fully audited for `HttpOnly` attributes.
- **WAF Configuration**: Cloudflare/WAF settings mentioned in docs but not visible in repo configuration.
