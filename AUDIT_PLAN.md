# Enterprise Readiness Audit Plan

## 1. Project Structure & Configuration Reconnaissance
*   List all files to understand the project layout and identify key configuration files.
*   Read `backend/app/settings.py`, `backend/app/infra/environment.py`, and `backend/Dockerfile`.
*   Read `web/next.config.js`, `web/package.json`, and `web/Dockerfile`.
*   Read `.github/workflows/` to list all CI/CD workflows.

## 2. Backend Enterprise Audit (Security, Isolation & Scalability)
*   **Tenant Isolation:** Verify `org_id` propagation in `backend/app/infra/org_context.py` and check for RLS policies in `backend/app/infra/migrations/`. Confirm `ContextVar` usage for async safety.
*   **Database Safety & Performance:** Inspect `backend/app/infra/db.py` for connection pool settings. Search for potential N+1 query patterns or unbounded list endpoints in `backend/app/api/`.
*   **Trust Boundary Audit:**
    *   Verify proxy-only trust boundaries:
        *   Direct API access cannot bypass proxy-based authentication.
        *   Forwarded headers (X-Forwarded-Proto / X-Forwarded-For) are trusted only from the reverse proxy.
        *   Admin proxy auth headers cannot be spoofed when hitting the API directly (host port, internal network, etc.).
    *   Identify exact enforcement points in code/config (middleware, dependency injection, Caddy config, env flags).
*   **Secret Management:** Verify `SecretStr` usage in `backend/app/settings.py` and ensure no default values exist for critical production secrets.
*   **Background Jobs:** Inspect worker configuration (e.g., `backend/app/worker.py` or similar) for retry logic, exception handling, and isolation.
*   **Abuse & Edge-case Resilience:**
    *   Verify protections against:
        *   large payload abuse / memory exhaustion (uploads, request bodies)
        *   brute-force / repeated login attempts
        *   burst traffic / rate limit coverage
        *   background job retry storms (amplification)
        *   DB pool exhaustion / connection storms
    *   Require concrete verification points (middleware, limits, timeouts, retry policies).

## 3. Web/Frontend Enterprise Audit
*   **CSP & Security Headers:** Analyze `web/next.config.js` and middleware for Content Security Policy strictness (check for `unsafe-inline`, `unsafe-eval`).
*   **Config Exposure:** Grep for `NEXT_PUBLIC_` variables in `web/` to ensure no sensitive secrets are exposed to the client.
*   **Auth & Session Management:** Inspect authentication logic (likely in `web/app/api/auth/` or `web/lib/auth.ts`) to verify token storage mechanisms (HttpOnly cookies vs localStorage) and SSR boundaries.
*   **Build & Dependencies:** Verify `web/Dockerfile` uses multi-stage builds and `npm prune --production`. Check `package.json` for dependency pinning.

## 4. CI/CD & Supply Chain Security Audit
*   **Action Pinning:** Inspect all files in `.github/workflows/` to verify that third-party actions are pinned by commit SHA, not tags.
*   **Installer Safety:** Check workflows for `curl | sh` or `wget | sh` patterns and verify if checksums or strict sources are used.
*   **Security Gates:** Verify the presence and configuration of scanners (Trivy, Grype, Bandit, Gitleaks). Check exit code policies (fail on vulnerabilities).
*   **Data Leakage Surface Audit:**
    *   Verify logs/artifacts do not leak:
        *   secrets, tokens, cookies, auth headers
        *   PII (emails, phone, addresses) in inappropriate contexts
    *   Specifically review:
        *   uploaded artifacts (coverage.xml, SBOMs, trivy/grype logs, compose logs)
        *   debug path steps / env dumps in CI
        *   production error responses/stack traces sanitization
    *   Output must name the concrete file paths checked.
*   **Artifacts & SBOM:** Check if SBOMs are generated and if build artifacts are properly handled (e.g., uploaded, signed).

## 5. Infrastructure & Operations Audit
*   **Container Resilience:** Inspect `docker-compose.yml` and `docker-compose.prod.yml` (if exists) for health checks (distinguishing liveness vs readiness), resource limits (CPU/Memory), and restart policies.
*   **Graceful Shutdown:** Verify `backend/app/main.py` and `web/server.js` (if custom) for SIGTERM/SIGINT handling to ensure zero-downtime deployments.
*   **Disaster Recovery & Durability:**
    *   Verify evidence of backup strategy and restore procedure:
        *   scripts, docs, cron/systemd jobs, storage location, retention assumptions
    *   Verify migration rollback safety / downgrade strategy:
        *   alembic practices, single-head guard, manual rollback notes
    *   Verify init scripts are idempotent and safe (WAL archive init, permissions).
*   **Observability:** Verify structured logging configuration (JSON format) in `backend/app/infra/logging.py`. Check for metrics endpoints (Prometheus) and tracing setup.

## 6. Synthesis & Reporting
*   Synthesize all findings into a structured "Enterprise Readiness Audit Report".
*   **Maturity Level:** Classify the system (Prototype -> Enterprise).
*   **Verified Strengths:** List solid components with file references.
*   **Critical Gaps:** Rank P0 (Blockers), P1 (High), P2 (Medium).
*   **Risk Assessment:** Evaluate Security, Data Isolation, Ops, and Scaling risks.
*   **Readiness Checklist:** Score Config, Secrets, CI, Security, DB, Auth, Observability, DR, Deployment.
*   **Roadmap:** Create a phased plan (Phase A: Safety, Phase B: Hardening, Phase C: Enterprise).
*   **Go/No-Go Verdict:** Provide explicit recommendations for Pilot, Standard, and Enterprise production.
