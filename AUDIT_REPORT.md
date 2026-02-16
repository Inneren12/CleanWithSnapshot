# Repo Audit Report: CleanWithSnapshot

**Date:** 2026-01-26
**Auditor:** Jules (Staff+ Engineer / QA Lead)
**Scope:** Architecture, CI/CD, Security, E2E, DB, Operations

---

## 1. Executive Summary

**Overall Health:**
The repository contains a mature, multi-tenant SaaS application with a sophisticated stack (Next.js, FastAPI, Caddy, Postgres RLS). However, the CI/CD pipeline and E2E testing harness exhibit **high brittleness**, leading to false negatives and developer friction. Security scanning is implemented but prone to "tool failures" (exit code 2) rather than legitimate vulnerability detection.

**Top 3 Risks:**
1.  **Brittle E2E Environment Generation (P0):** The current method of generating CI environment variables by regex-scraping `backend/app/settings.py` is extremely fragile. It risks missing critical secrets or misconfiguring the E2E stack, leading to hard-to-debug authentication failures.
2.  **CI Security Scanning Instability (P1):** Reliance on potentially mismatched Docker API versions or socket permissions causing Grype/Trivy to crash (exit code 2) rather than report. This blocks releases unpredictably.
3.  **Routing & Auth Configuration Drift (P1):** Discrepancies between local dev (`.env`), CI (`.env.e2e.ci`), and Prod configs regarding `ADMIN_PROXY_AUTH` and base URLs cause Playwright to fail with "404 Not Found" (HTML response) when it expects API JSON.

---

## 2. Architecture Overview

The system follows a standard containerized 3-tier architecture with a reverse proxy for TLS and routing.

**Core Services:**
*   **Proxy (`caddy`)**: Entry point (Ports 80/443). Routes `/v1/*` to API and `/*` to Web. Handles auto-HTTPS.
*   **Web (`cleanwithsnapshot-web`)**: Next.js 14 App Router. SSR + Client components. Communicates with API via `NEXT_PUBLIC_API_BASE_URL`.
*   **API (`cleanwithsnapshot-api`)**: FastAPI (Python 3.11). Stateless REST API. Enforces RLS via SQLAlchemy.
*   **Database (`db`)**: PostgreSQL 16. Uses Row-Level Security (RLS) for tenant isolation (`org_id`).
*   **Async/Jobs (`jobs`)**: Background worker for emails, reports, and cleanup.
*   **Cache (`redis`)**: Rate limiting, session storage, and simple caching.

**Critical Paths:**
*   **User Traffic**: `User -> Caddy -> Web (SSR) -> Caddy -> API -> DB`
*   **Admin Traffic**: `Admin -> Caddy -> Web -> API (Protected by Proxy Auth + Session) -> DB`

---

## 3. CI Findings

**Workflow:** `.github/workflows/ci.yml`

| Severity | Finding | Evidence / Root Cause |
| :--- | :--- | :--- |
| **High** | **Grype "Tool Failure" vs "Vuln Found"** | Grype often exits with code 2 (runtime error) instead of 1 (policy violation) when talking to Docker daemons in CI. <br> *Fix:* Scan SBOMs/tarballs exclusively, avoid direct Docker daemon calls in scan steps. |
| **Medium** | **Duplicate YAML Keys in Compose** | `docker-compose.e2e.yml` has had duplicate keys (e.g., `caddy:` defined twice), triggering "YAML guardrail" failures or undefined behavior. |
| **Medium** | **Docker Image Tag Reuse** | CI builds `cleanwithsnapshot-api:ci` and potentially overwrites it or uses a stale layer if build caching is aggressive. Unique tags per run (SHA) are safer. |

**Recommendations:**
*   **Stable Scanning**: Continue the pattern of `docker save -> tar -> syft -> sbom -> grype/trivy`. This eliminates Docker socket compatibility issues.
*   **Strict Exit Codes**: Explicitly handle exit code 2 as a "CI Infra Failure" (retryable) vs exit code 1 as "Security Block" (requires fix).

### **Grype/Trivy Exit Code Matrix**

| Exit Code | Meaning | Action |
| :--- | :--- | :--- |
| **0** | Clean (no critical vulnerabilities found). | **Pass** |
| **1** | Vulnerabilities found >= cutoff (Policy Fail). | **Block** (Requires fix/waiver) |
| **2** | Tool/Scanner Failure (Infra Fail). | **Fail** (Retry job, check logs) |
| **Other** | Unexpected Tool Error. | **Fail** (Investigate) |

**Key Directive:** Use **SBOM scanning** (via `syft` or `trivy image --format spdx-json`) instead of direct Docker socket scanning to eliminate "docker api too old / scanner execution failed" errors.

---

## 4. E2E Findings (Playwright)

**Workflow:** `.github/workflows/e2e.yml`

| Severity | Finding | Evidence / Root Cause |
| :--- | :--- | :--- |
| **Critical** | **Regex-based Env Generation** | `python - <<'PY' ... re.findall(...)` in `e2e.yml` scrapes `settings.py` to build `.env.e2e.ci`. This is fragile; if variable definitions span lines or change quoting, CI breaks. |
| **High** | **Proxy Auth Header Missing** | E2E requires `ADMIN_PROXY_AUTH_REQUIRED=true`. If Playwright context setup fails to inject headers (`X-Admin-User`, etc.), requests return 401 or 403, often masked as 404s by Next.js error pages. |
| **Medium** | **DB Healthcheck Flakes** | `pg_isready` check in CI loop sometimes passes before the app is fully ready to accept connections, or fails if the container restarts. |
| **Medium** | **Routing Ambiguity** | `NEXT_PUBLIC_API_BASE_URL` in CI is often set to `http://api:8000` (docker internal), but browser tests (Playwright) run on host network or mapped ports, needing `http://127.0.0.1:3000/v1`. |

**Recommendations:**
*   **Deterministic Env**: Replace regex scraping with a dedicated `e2e.env.template` or a script that imports `Settings` and exports defaults.
*   **Fail-Fast Preflight**: Add a curl check in CI that explicitly verifies `X-Admin-User` authentication works against `/v1/admin/profile` *before* starting Playwright.

### **E2E Base URL Source of Truth**

To ensure consistency and prevent "404 HTML" errors, the following environment variables must be strictly enforced in CI/E2E:

*   **`PLAYWRIGHT_BASE_URL`**: `http://127.0.0.1:3000` (via Caddy, simulating user traffic).
*   **`PLAYWRIGHT_API_BASE_URL`**: `http://127.0.0.1:3000` (via Caddy, ensuring `/v1/*` routing works correctly).
    *   *Note:* Accessing port `8000` directly bypasses Caddy routing and may fail if the API relies on headers injected by Caddy (e.g., `X-Forwarded-Proto`).
*   **Direct API Access (Port 8000)**: If tests *must* access port 8000 directly, they must explicitly send required Proxy Auth headers (`X-Admin-User`, etc.) or Basic Auth credentials if `LEGACY_BASIC_AUTH_ENABLED=true`. Otherwise, the API will reject requests with "Invalid proxy authentication".

**Preflight Check Command:**
```bash
curl -sS -i http://127.0.0.1:3000/v1/admin/profile
```
*Expected Result:* HTTP 200 OK with `Content-Type: application/json` (not `text/html`).

---

## 5. Security Scan Findings (Trivy/Grype)

**Current State:**
*   Pipelines run Trivy and Grype.
*   Uses `TRIVY_SEVERITY: CRITICAL`.
*   Uses `GRYPE_FAIL_ON: critical`.

**Issues:**
*   **False Positives**: Python/Node base images often have "won't fix" CVEs.
*   **Missing Artifacts**: If the tool crashes (exit 2), no report is generated, but the step might be interpreted ambiguously if not careful.

**Recommendations:**
*   **Input Standardization**: Always scan the **SBOM** (SPDX/CycloneDX) generated by Syft. This is faster and more stable than scanning images directly.
*   **Ignore Policy**: Maintain a `.trivyignore` and `.grype.yaml` (allowlist) for "won't fix" vulnerabilities to keep the board clean.

---

## 6. DB & Migrations Findings

**Current State:**
*   Alembic for migrations.
*   RLS audit script exists (`scripts/audit_rls_coverage.py`).

**Risks:**
*   **Schema Drift**: `alembic heads` check is good, but `alembic merge` is manual.
*   **RLS Gaps**: If a new table is added without RLS, it might expose data if the audit script isn't run in strict mode in CI.

**Recommendations:**
*   **Enforce RLS Audit**: Ensure `rls-audit` job in `ci.yml` blocks merging if core tables are missing RLS.
*   **Migration Linting**: Enforce `down_revision` linearity or auto-merge heads check.

---

## 7. Operations & Deploy Findings

*   **Deploy Script**: `ops/deploy.sh` is solid but relies on SSH/git pull.
*   **Secrets**: Secrets are in `.env` on the server. No secret manager integration visible in the basic deploy script (though `settings.py` supports AWS Secrets Manager).

**Recommendations:**
*   **Immutable Artifacts**: Move towards deploying Docker images (tags) rather than building from source on the production server.

---

## 8. Prioritized Backlog

| Priority | ID | Component | Summary | Proposed Fix |
| :--- | :--- | :--- | :--- | :--- |
| **P0** | **E2E-01** | **CI / E2E** | **Fix Brittle Env Generation** | Remove regex scraping. Use `scripts/generate_ci_env.py` that loads Pydantic settings or strict template. |
| **P0** | **SEC-01** | **CI / Security** | **Stabilize Grype/Trivy** | Switch pipelines to strictly scan tarballs/SBOMs. Handle Exit Code 2 as infra failure. |
| **P1** | **E2E-02** | **Playwright** | **Proxy Auth Reliability** | Centralize auth header injection in `playwright.config.ts`. Add preflight curl check in CI. |
| **P1** | **CI-01** | **Workflow** | **Fix YAML Duplicates** | Audit and clean `docker-compose.e2e.yml` to remove duplicate keys. |
| **P2** | **DB-01** | **Migrations** | **Strict RLS Gate** | Ensure RLS audit fails CI for *any* new table missing `org_id` policies. |
| **P2** | **OPS-01** | **Logging** | **Reduce CI Noise** | Tune log levels for `api` and `web` in CI to focus on errors/warnings. |

---

## 9. PR Plan

### **PR-01: Fix CI YAML & Env Generation (The "Stability" PR)**
*   **Scope:** `backend/scripts/`, `.github/workflows/e2e.yml`, `docker-compose.e2e.yml`
*   **Changes:**
    *   Create `backend/scripts/generate_e2e_env.py` (imports `Settings`, dumps safe defaults + secrets).
    *   Update `e2e.yml` to use this script instead of inline Python regex.
    *   Remove duplicate keys from `docker-compose.e2e.yml`.
*   **Verification:** CI "Generate Env" step passes reliably.

### **PR-02: Robust Security Scanning (The "Security" PR)**
*   **Scope:** `.github/workflows/ci.yml`
*   **Changes:**
    *   Refactor `container-scan` and `grype-scan` jobs.
    *   Ensure `docker save` -> `api.tar`.
    *   `syft api.tar -o spdx-json > api.sbom`.
    *   `grype sbom:api.sbom`.
    *   Add logic to retry on Exit Code 2 or fail with "Infra Error".
*   **Verification:** CI passes scan step even if Docker socket is flaky.

### **PR-03: E2E Network & Preflight Hardening**
*   **Scope:** `.github/workflows/e2e.yml`, `web/e2e/playwright.config.ts`
*   **Changes:**
    *   Add `curl` preflight step to verify Admin API is reachable and Auth works *before* Playwright starts.
    *   Update Playwright config to strictly use `ADMIN_PROXY_AUTH` headers from env.
*   **Verification:** E2E logs show successful preflight; "404 Not Found" errors decrease.

---

## 10. Golden Repro Commands

### **1. Local Bring-up (Full Stack)**
```bash
# Start DB, Redis, API, Web, Caddy
docker compose up -d --build

# Verify Health
curl -v http://localhost:8000/healthz
curl -v http://localhost:3000/healthz
```

### **2. Routing Verification (via Caddy)**
```bash
# Verify API routing through Caddy (should return JSON, not HTML)
curl -v http://localhost:80/v1/healthz

# Verify Proxy Auth (if enabled)
curl -v -H "X-Admin-User: admin" -H "X-Admin-Roles: admin" http://localhost:80/v1/admin/profile
```

### **3. Manual Security Scan (Tar/SBOM method)**
```bash
# 1. Build
docker compose build api

# 2. Save
docker save cleanwithsnapshot-api:latest -o api.tar

# 3. Generate SBOM
syft docker-archive:api.tar -o spdx-json > api.sbom.json

# 4. Scan with Grype
grype sbom:api.sbom.json --fail-on critical

# 5. Scan with Trivy
trivy image --input api.tar --severity CRITICAL
```

### **4. E2E Env Generation (New Script Test)**
```bash
cd backend
# Simulates what CI will do
APP_ENV=ci python scripts/generate_e2e_env.py > .env.e2e.ci
```
