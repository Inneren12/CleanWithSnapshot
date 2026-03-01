# E2E Test Suite Failure Report

This document reports the current state of the CleanWithSnapshot E2E test suite.

## Summary Table

| Test Name | File | Error | Suspected Cause |
| :--- | :--- | :--- | :--- |
| Any e2e test | `backend/tests/` | `ModuleNotFoundError: No module named 'pytest_asyncio'` | `pytest-asyncio` is missing from `requirements.txt` / environment, despite the code trying to import it. |
| All 50 Web E2E tests | `web/e2e/tests/*.spec.ts` | `Error: apiRequestContext.get: connect ECONNREFUSED 127.0.0.1:3000` | E2E environment is not spinning up correctly. Services (like db and redis) are failing to pull or launch due to Docker Hub rate limits (`You have reached your unauthenticated pull rate limit`), and so the backend API and frontend servers are unavailable. |
| Alembic Migrations | `backend/alembic/versions/` | `ValidationError: 1 validation error for Settings` | Missing environment variables required by Pydantic `Settings` (e.g. `AUTH_SECRET_KEY`, `CLIENT_PORTAL_SECRET`, `WORKER_PORTAL_SECRET`, `ADMIN_PROXY_AUTH_E2E_ENABLED`). |

## 1. Database Migrations

* **What is broken:** Running `alembic check` fails.
* **Where in the code:** `backend/app/settings.py` (Pydantic `Settings` model).
* **Evidence:** The application strictly requires several environment variables for secrets and environment configurations (e.g., `APP_ENV=dev`, `AUTH_SECRET_KEY`, `ADMIN_PROXY_AUTH_SECRET`, etc.). The E2E script `scripts/generate_e2e_env.py` handles some, but running `alembic check` natively requires passing them in manually, which results in either a validation error or database connection failure (if DB is not running).
* **Migrations status:** Running `analyze_migrations.py` revealed that the migrations are correctly formed with a single head (`merge_20260224_01_merge_heads.py`), but with 22 branching points due to extensive merge heads (which is normal for this repo).

## 2. HTTP Headers

* **What is broken:** While not directly causing failures right now (because the server is unreachable), `X-Test-Org` and `Authorization` headers are highly critical. E2E tests leverage the `X-Proxy-Auth-Secret` and proxy headers to bypass normal authentication flows.
* **Where in the code:** `web/e2e/tests/helpers/adminAuth.ts` and `web/e2e/tests/helpers/dataRightsApi.ts`.
* **Evidence:** The E2E tests use `buildProxyHeaders` which dynamically injects headers such as `X-Proxy-Auth-Secret`, `X-Auth-MFA`, `X-E2E-Admin-User`, etc.

## 3. CORS Configuration

* **What is broken:** Could not be fully tested in Playwright due to ECONNREFUSED.
* **Where in the code:** `backend/app/settings.py` -> `CORS_ORIGINS`.
* **Evidence:** The application normally expects Playwright to be tested against `127.0.0.1:3000` while communicating with `127.0.0.1:8000`. If `CORS_ORIGINS` does not explicitly allow `http://127.0.0.1:3000`, the preflight OPTIONS request will fail.

## 4. Rate Limiting

* **What is broken:** Docker Pull Rate limit reached.
* **Where in the code:** Initializing the test environment (`docker compose up`).
* **Evidence:** `error from registry: You have reached your unauthenticated pull rate limit. https://www.docker.com/increase-rate-limit`. This prevents the database and redis containers from spinning up.

## 5. Auth/Org Context

* **What is broken:** Could not be directly observed due to the environment failure.
* **Where in the code:** API endpoints requiring `current_org_id`.
* **Evidence:** The proxy auth helpers in `web/e2e/tests/helpers/adminAuth.ts` handle `X-E2E-Admin-Roles` and proxy auth secrets, but if an endpoint expects an explicit `X-Test-Org` header to set the organization context (as seen in memory) and it is missing, it will default to the user's default org or fail with 401/403.
