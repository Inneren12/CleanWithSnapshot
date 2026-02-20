# Enterprise Audit Report: CleanWithSnapshot

## 1. Current State Assessment (Where are we?)

### Architectural Slice
*   **Structure:** Robust Domain-Driven Design (DDD) in FastAPI backend (`backend/app`). Routes (`api/`) delegate to services (`domain/`), which interact with infrastructure (`infra/`). Excellent separation of concerns.
*   **Code Quality:** High. Strict Python typing (mypy/pyright compatible), Pydantic validation, and RFC 7807 error handling (`app/api/problem_details.py`).
*   **Data Isolation:** Multi-tenancy enforced via PostgreSQL Row-Level Security (RLS) (`app/infra/org_context.py`), a gold standard for SaaS security.
*   **Async Correctness:** Generally good, but a **CRITICAL DoS vulnerability** exists in `routes_orders.py` where files are read entirely into memory (`await file.read()`).

### Infrastructure & Deployment
*   **Containerization:** Production-ready Dockerfiles (non-root users, multi-stage builds).
*   **Orchestration:** Docker Compose used for both dev and prod. Lack of Kubernetes/ECS limits scalability and zero-downtime updates.
*   **CI/CD:** Exemplary GitHub Actions pipeline (`.github/workflows/ci.yml`) including Ruff, Pytest, Vitest, Trivy (Container), Grype (SBOM), Bandit (SAST), Gitleaks (Secrets), and RLS Audit.

## 2. Gap Analysis (The Road to Enterprise)

### Security
*   **Strengths:** Secret Management (`pydantic-settings` + `SecretStr`), Authentication (Admin/MFA vs App/Worker), RLS enforcement.
*   **Weaknesses:**
    *   **Frontend Security:** Next.js (`web/next.config.mjs`) lacks Content Security Policy (CSP) headers, leaving it vulnerable to XSS.
    *   **File Uploads:** Memory exhaustion vector in `upload_order_photo`.

### Observability
*   **Strengths:** Structured JSON logging with PII redaction (`app/infra/logging.py`), OpenTelemetry tracing, Prometheus metrics (`/metrics`).
*   **Weaknesses:**
    *   **Frontend Observability:** No integration with frontend error tracking tools (e.g., Sentry, LogRocket).

### Resilience & Scalability
*   **Strengths:** PostgreSQL 16 with connection pooling, Redis for rate limiting/caching.
*   **Weaknesses:**
    *   **Job Queue:** Custom `app.jobs.run` loop is a single point of failure and difficult to scale compared to Celery/ARQ.
    *   **Backups:** WAL archiving is configured locally (`archive_command`) but lacks automated offsite sync (e.g., to S3). Disk failure = Data Loss.

## 3. Production Readiness Blockers (Critical)

1.  **DoS Vulnerability in File Uploads:**
    *   *Location:* `backend/app/api/routes_orders.py`
    *   *Issue:* `await file.read()` loads entire file into RAM.
    *   *Fix:* Stream file to storage using `shutil.copyfileobj` or `upload_fileobj`.

2.  **Data Loss Risk (Backups):**
    *   *Location:* `docker-compose.yml`
    *   *Issue:* PostgreSQL WAL archives are stored on a local volume without offsite sync.
    *   *Fix:* Add sidecar container (e.g., `wal-g`) to sync `/var/lib/postgresql/wal_archive` to S3/R2.

3.  **Missing Frontend Security Headers:**
    *   *Location:* `web/next.config.mjs`
    *   *Issue:* No Content Security Policy (CSP).
    *   *Fix:* Configure `next-secure-headers` or strict `headers()` in `next.config.mjs`.

## 4. Actionable Roadmap

### Phase 1: Stabilization & Prod-Ready (Immediate)
- [ ] Fix `upload_order_photo` to use streaming uploads.
- [ ] Add sidecar container for WAL archive sync to S3.
- [ ] Implement CSP in Next.js.
- [ ] Verify disaster recovery (restore from S3).

### Phase 2: Enterprise Foundations (1-3 Months)
- [ ] Replace custom `jobs` runner with **ARQ** (Redis-based) or **Celery**.
- [ ] Implement Blue/Green deployment to enable zero-downtime updates.
- [ ] Add frontend error tracking (Sentry).

### Phase 3: Future-Proofing (3+ Months)
- [ ] Migrate to Kubernetes (EKS/GKE) for multi-node scaling.
- [ ] Extract heavy processing (PDF/Image) into serverless functions.
