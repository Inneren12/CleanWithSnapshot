# Enterprise & Production Readiness Audit Report

**Repository:** CleanWithSnapshot / PaniDobro
**Audit Date:** 2026-01-30
**Previous Audit:** 2026-01-18
**Auditor:** Claude Code (Automated Assessment)
**Branch:** main

---

## 1. Executive Summary

### Current State Scores (0-10)

| Dimension | Score | Assessment |
|-----------|-------|------------|
| **Multi-tenancy** | 8/10 | RLS on core tables; context propagation implemented; isolation tests present |
| **Modularity** | 7/10 | 61 domain modules; feature flags per-tenant; coupling hotspots exist |
| **Security** | 8/10 | Strong auth stack; RBAC; audit logging; admin hardening; supply chain controls |
| **Observability** | 8/10 | Prometheus metrics; SLO alerts; Grafana dashboards; structured logging |
| **CI/CD** | 9/10 | Comprehensive gates; container scans; E2E; RLS audit; SBOM generation |
| **DR/Ops** | 8/10 | PITR drills; runbooks; blue-green deploy; rollback scripts |
| **Test Coverage** | 8/10 | 239 test files; 9 E2E specs; postgres isolation tests |
| **Documentation** | 9/10 | 155+ docs; 20 runbooks; security docs; SLOs defined |

**Overall Production Readiness: 8.1/10 - READY for SMB production with minor gaps**

### Progress Since Previous Audit (2026-01-18)

| Gap from Previous Audit | Status | Evidence |
|-------------------------|--------|----------|
| No automated integration/e2e tests | **FIXED** | 9 Playwright E2E specs in `web/e2e/tests/`, E2E CI job in `.github/workflows/e2e.yml` |
| Missing dependency scanning | **FIXED** | Trivy, Grype, Gitleaks in CI; SBOMs generated |
| No observability/SLO tracking | **FIXED** | Grafana+Loki+Tempo stack; SLO burn-rate alerts in `prometheus/rules/` |
| No database backup automation | **FIXED** | PITR drills in `ops/pitr_restore_drill.sh`, WAL archiving documented |
| No load/performance testing | **FIXED** | k6 load tests in CI (`perf-baseline` job) |
| Dependabot not configured | **PARTIAL** | Supply chain hardened but Dependabot/Renovate not visible |

### Top 5 Risks Blocking Production/Enterprise

| # | Risk | Severity | Evidence |
|---|------|----------|----------|
| 1 | **RLS coverage partial** | Medium | Only 9 tables have RLS; `client_users`, `notifications_*`, `checklists` missing (`backend/alembic/versions/0044_postgres_rls_org_isolation.py`) |
| 2 | **Feature flag percentage rollout missing** | Low | Boolean per-org toggles only; no cohort/percentage targeting (`backend/app/domain/feature_modules/service.py:316`) |
| 3 | **E2E test coverage limited** | Medium | 9 spec files; critical paths covered but missing finance/subscriptions flows (`web/e2e/tests/`) |
| 4 | **Break-glass MFA not enforced** | Medium | MFA required only "for roles in admin_mfa_required_roles" - needs validation (`docs/BREAK_GLASS.md:11`) |
| 5 | **Warnings audit gated but permissive** | Low | `--gate fail` in CI but allowlist in `noise_allowlist.json` may mask issues |

### Top 5 Fastest Wins (Next 14 Days)

| # | Win | Effort | Impact |
|---|-----|--------|--------|
| 1 | Extend RLS to `client_users`, `notifications_center`, `checklists` | S | Critical isolation gap closed |
| 2 | Add E2E tests for invoice payment flow and subscription management | M | Reduces regression risk |
| 3 | Document MFA enforcement matrix for all admin roles | S | Compliance evidence |
| 4 | Add feature flag percentage rollout (10/25/50/100%) | M | Safer deployments |
| 5 | Create ADR for module API contracts | S | Platform evolution safety |

---

## 2. "What's Done" Matrix (Evidence-Based)

### Core Capabilities

| Capability | Status | Evidence | Risks |
|------------|--------|----------|-------|
| **Multi-tenant org isolation** | DONE | `backend/alembic/versions/0044_postgres_rls_org_isolation.py` - RLS policies on 9 tables | Some tables missing RLS |
| **org_id on core tables** | DONE | `backend/scripts/audit_rls_coverage.py` - CI enforced | - |
| **Request org context** | DONE | `backend/app/api/org_context.py`, `backend/app/infra/org_context.py` | - |
| **DB session RLS wiring** | DONE | `backend/app/infra/db.py:115` - SET LOCAL on begin | - |
| **RBAC permission catalog** | DONE | `backend/app/domain/iam/permissions.py` - 27 permissions, 7 roles | - |
| **Admin proxy auth** | DONE | `backend/app/api/admin_auth.py` - trusted proxy + E2E mode | - |
| **Admin IP allowlist** | DONE | `backend/app/api/admin_safety.py:84-101` | - |
| **Break-glass emergency access** | DONE | `docs/BREAK_GLASS.md`, `backend/app/api/break_glass.py` | MFA enforcement unclear |
| **Immutable audit logs** | DONE | `docs/ADMIN_ACTION_AUDIT.md`, `backend/app/domain/admin_audit/` | - |
| **Feature flag audit trail** | DONE | `docs/FEATURE_FLAG_GOVERNANCE.md`, `backend/app/domain/feature_flag_audit/` | - |
| **Audit retention + legal hold** | DONE | `docs/AUDIT_RETENTION_POLICY.md` - 3yr admin, 7yr config | - |
| **Config audit logging** | DONE | `backend/app/domain/config_audit/` | - |
| **Integration audit logging** | DONE | `backend/app/domain/integration_audit/` | - |
| **Per-tenant feature modules** | DONE | `backend/app/domain/feature_modules/service.py` - 16 modules, 26 subfeatures | No percentage rollout |
| **Feature flag lifecycle** | DONE | `docs/FEATURE_FLAG_GOVERNANCE.md` - draft/active/expired/retired | - |
| **Stale flag detection** | DONE | Evaluation telemetry + scheduled job | - |
| **WAF/rate limiting** | DONE | `docs/SECURITY_WAF_BASELINE.md`, `docs/SECURITY_RATE_LIMITS.md` | - |
| **Secrets backend** | DONE | `docs/SECRETS_BACKEND.md` - AWS Secrets Manager, env fallback | - |
| **Prod config validation** | DONE | `.github/workflows/ci.yml:208-261` - fail-closed on missing secrets | - |
| **Container scanning** | DONE | Trivy + Grype in CI, CRITICAL gate | - |
| **SBOM generation** | DONE | Syft SPDX-JSON per image | - |
| **Secrets scanning** | DONE | Gitleaks in CI | - |
| **SAST (Bandit)** | DONE | High-severity Python scan | - |
| **SLO definitions** | DONE | `docs/SLO.md` - 99% availability, p95 < 300ms | - |
| **Burn-rate alerts** | DONE | `prometheus/rules/slo_alerts.yml` | - |
| **Prometheus metrics** | DONE | `docs/OBSERVABILITY.md`, `/metrics` endpoint | - |
| **Grafana dashboards** | DONE | `observability/grafana/` | - |
| **Loki logging** | DONE | `observability/loki/` | - |
| **Tempo tracing** | DONE | `observability/tempo/` | - |
| **Deploy runbook** | DONE | `docs/DEPLOY_RUNBOOK.md` | - |
| **Rollback runbook** | DONE | `docs/ROLLBACK_RUNBOOK.md` | - |
| **Disaster recovery** | DONE | `docs/DISASTER_RECOVERY.md` - PITR, WAL archiving | - |
| **PITR drill automation** | DONE | `ops/pitr_restore_drill.sh` | - |
| **Blue-green deploy** | DONE | `ops/blue-green-deploy.sh` | - |
| **Canary deploy** | DONE | `ops/deploy_canary.sh` | - |
| **Incident runbooks** | DONE | 20 runbooks in `docs/runbooks/` | - |

### Partial/In Progress

| Capability | Status | Evidence | Gap |
|------------|--------|----------|-----|
| **RLS on all org-scoped tables** | PARTIAL | 9/~20+ tables covered | Need `client_users`, `notifications_*`, `checklists`, etc. |
| **Percentage rollout** | PARTIAL | Boolean only | No 10/25/50% cohort targeting |
| **E2E test coverage** | PARTIAL | 9 spec files | Missing finance, subscriptions, data rights flows |
| **MFA enforcement matrix** | PARTIAL | Documented but not validated | Need test coverage |
| **Module API contracts** | NOT STARTED | No formal contract definitions | Need ADR + enforcement |
| **Franchise/white-label** | NOT STARTED | Per-tenant feature flags exist | No branding/theming layer |

---

## 3. Architecture & Modularity Assessment

### Classification: **Modular Monolith**

**Evidence:**
- Single deployable (`backend/app/main.py`)
- 61 domain modules (`backend/app/domain/`)
- Shared database with per-table RLS
- No service mesh or inter-service communication
- Feature flags for per-tenant module enablement

### Domain Module Inventory (61 modules)

```
backend/app/domain/
├── access_review/      # Compliance access reviews
├── addons/             # Booking add-on services
├── admin_audit/        # Admin action logging
├── admin_idempotency/  # Idempotent admin operations
├── analytics/          # Business analytics
├── audit_retention/    # Audit log lifecycle
├── availability/       # Worker availability
├── bookings/           # Core booking domain ★
├── bot/                # Chatbot logic
├── break_glass/        # Emergency access
├── chat/               # Real-time chat
├── chat_threads/       # Threaded conversations
├── checklists/         # Job checklists
├── clients/            # Client management ★
├── config/             # Org configuration
├── config_audit/       # Config change audit
├── dashboard/          # Dashboard aggregations
├── data_retention/     # Data lifecycle
├── data_rights/        # GDPR/CCPA exports
├── dispatcher/         # Job assignment
├── disputes/           # Payment disputes
├── documents/          # Document storage
├── export_events/      # Event export queue
├── feature_flag_audit/ # Flag change audit
├── feature_flags/      # Flag definitions
├── feature_modules/    # Per-org module toggles
├── finance/            # Financial reports
├── iam/                # Identity & access
├── integration_audit/  # Integration change audit
├── integrations/       # Third-party integrations
├── inventory/          # Supply inventory
├── invoices/           # Invoice management ★
├── leads/              # Lead management ★
├── leads_nurture/      # Lead nurture campaigns
├── leads_scoring/      # Lead scoring
├── logs/               # Event logging
├── marketing/          # Marketing campaigns
├── message_templates/  # Template management
├── notifications/      # Notification dispatch
├── notifications_center/ # Notification inbox
├── notifications_digests/ # Digest emails
├── nps/                # Net promoter score
├── ops/                # Operational tools
├── org_settings/       # Org preferences
├── outbox/             # Transactional outbox
├── policy_overrides/   # Policy exceptions
├── pricing/            # Pricing engine
├── pricing_settings/   # Pricing config
├── quality/            # Quality management
├── queues/             # Job queues
├── reason_logs/        # Change reason tracking
├── rules/              # Automation rules
├── saas/               # SaaS identity
├── soft_delete_purge/  # Soft delete lifecycle
├── storage_quota/      # Storage limits
├── subscriptions/      # Recurring bookings
├── teams/              # Team management
├── time_tracking/      # Time entry
├── timeline/           # Activity timeline
├── training/           # Worker training
└── workers/            # Worker management ★
```

★ = Core tables with RLS

### Coupling Hotspots

| Hotspot | Evidence | Risk |
|---------|----------|------|
| `bookings` ↔ `invoices` | Shared models, foreign keys | Medium - migration coupling |
| `feature_modules` ↔ `feature_flags` | Service cross-imports | Low - intentional |
| `admin_audit` ← all domains | Audit service imported everywhere | Low - centralized by design |
| `infra/db.py` | All domains depend on session factory | Low - infrastructure layer |

### Platform Contracts Readiness

**Current State:** No formal API contracts between modules.

**Recommendation:** Each domain module should define:
1. **Public service API** - exported functions in `service.py`
2. **Internal helpers** - prefixed with `_`
3. **Contract changelog** - breaking changes require deprecation cycle

**Proposed ADRs:**
1. `ADR-001-module-api-contracts.md` - Define contract boundaries and versioning
2. `ADR-002-breaking-change-policy.md` - Migration path for signature changes
3. `ADR-003-platform-expansion-principles.md` - Second vertical guidelines

### Feature Flag System Assessment

| Capability | Status | Evidence |
|------------|--------|----------|
| Per-tenant toggles | DONE | `OrgFeatureConfig.feature_overrides` |
| Module-level flags | DONE | `MODULE_KEYS` (16 modules) |
| Subfeature flags | DONE | `SUBFEATURE_KEYS` (26 subfeatures) |
| Lifecycle states | DONE | draft/active/expired/retired |
| Expiration enforcement | DONE | Expired flags auto-disable |
| Audit trail | DONE | Every change logged |
| Stale detection | DONE | Evaluation telemetry |
| Percentage rollout | NOT DONE | Not implemented |
| Cohort targeting | NOT DONE | Not implemented |
| A/B testing | NOT DONE | Not implemented |

### Platform Expansion Path

**For "Second Vertical" Readiness:**

1. **No folder reorganization required** - domain modules already isolated
2. **Abstraction layer needed:**
   - Extract `CleaningBooking` → generic `ServiceBooking` interface
   - Create `VerticalAdapter` pattern for pricing/scheduling
3. **Success criteria:**
   - New vertical can be enabled per-org via feature flag
   - Core scheduling/invoicing works without modification
   - Vertical-specific fields in JSON columns or separate tables

---

## 4. Multi-tenant & Franchise/White-label Readiness

### What Is Safe Today

| Aspect | Status | Evidence |
|--------|--------|----------|
| **Org-scoped data isolation** | Safe | RLS policies + context propagation |
| **Per-org feature toggles** | Safe | `OrgFeatureConfig` table |
| **Per-org settings** | Safe | `org_settings` module |
| **Separate login domains** | Safe | SaaS identity per org |
| **Audit segregation** | Safe | Audit logs include `org_id` |

### What Is Missing for Franchise/White-label

| Gap | Effort | Description |
|-----|--------|-------------|
| **Branding/theming** | M | No per-org logo, colors, custom CSS |
| **Custom domain support** | L | Certificate provisioning, DNS config |
| **Franchisee hierarchy** | L | No parent-child org relationships |
| **Revenue sharing** | M | No commission/royalty tracking |
| **Franchisor dashboard** | L | No cross-org aggregate views |
| **White-label email templates** | S | Templates exist but not per-org customizable |

### Incremental Path to Franchise Support

1. **Phase 1 (S):** Add `org_branding` table (logo_url, primary_color, company_name)
2. **Phase 2 (M):** Add `org_parent_id` for franchisor-franchisee relationship
3. **Phase 3 (M):** Build franchisor dashboard with cross-org aggregations (requires admin bypass for RLS)
4. **Phase 4 (L):** Custom domain with Caddy dynamic TLS

---

## 5. Production Readiness

### CI Gates Inventory

| Job | Type | Purpose | Evidence |
|-----|------|---------|----------|
| `api` | HARD | Backend unit tests + coverage | `.github/workflows/ci.yml:10-116` |
| `web` | HARD | TypeScript build + lint | `.github/workflows/ci.yml:118-170` |
| `web-vitest` | HARD | Frontend unit tests | `.github/workflows/ci.yml:172-206` |
| `api-prod-config` | HARD | Prod secrets validation | `.github/workflows/ci.yml:208-261` |
| `security` | HARD | Bandit SAST | `.github/workflows/ci.yml:263-305` |
| `rls-audit` | HARD | RLS coverage enforcement | `.github/workflows/ci.yml:307-376` |
| `container-scan` | HARD | Trivy CRITICAL gate | `.github/workflows/ci.yml:378-569` |
| `grype-scan` | HARD | Grype CRITICAL gate | `.github/workflows/ci.yml:571-691` |
| `secrets-scan` | HARD | Gitleaks secrets detection | `.github/workflows/ci.yml:694-710` |
| `infra` | HARD | Docker Compose validation | `.github/workflows/ci.yml:712-745` |
| `smoke-compose` | HARD | Integration smoke test | `.github/workflows/ci.yml:747-802` |
| `perf-baseline` | SOFT | Performance comparison (warn-only) | `.github/workflows/ci.yml:804-861` |
| `playwright` (E2E) | HARD | End-to-end tests | `.github/workflows/e2e.yml` |

### Runbooks Available (20 total)

| Runbook | Path |
|---------|------|
| API Down | `docs/runbooks/api-down.md` |
| DB Down | `docs/runbooks/db-down.md` |
| High Resource Usage | `docs/runbooks/high-resource-usage.md` |
| Backup Stale | `docs/runbooks/backup-stale.md` |
| Redis Down | `docs/runbooks/redis-down.md` |
| Job Scheduler Stale | `docs/runbooks/job-scheduler-stale.md` |
| Migrations Not Current | `docs/runbooks/migrations-not-current.md` |
| Disk Full | `docs/runbooks/disk-full.md` |
| Payment Webhook Failing | `docs/runbooks/payment-webhook-failing.md` |
| Email/SMS Provider Failing | `docs/runbooks/email-sms-provider-failing.md` |
| Break Glass Incident | `docs/runbooks/BREAK_GLASS_INCIDENT.md` |
| Stripe Incident | `docs/runbooks/STRIPE_INCIDENT.md` |
| Twilio Incident | `docs/runbooks/TWILIO_INCIDENT.md` |
| Admin Auth Alerts | `docs/runbooks/ADMIN_AUTH_ALERTS.md` |
| Rate Limit Abuse | `docs/runbooks/RATE_LIMIT_ABUSE.md` |
| Org Abuse Triage | `docs/runbooks/ORG_ABUSE_TRIAGE.md` |
| Outbox Backlog | `docs/runbooks/OUTBOX_BACKLOG.md` |
| Jobs Heartbeat | `docs/runbooks/JOBS_HEARTBEAT.md` |
| Quota Blocks | `docs/runbooks/QUOTA_BLOCKS.md` |

### Monitoring & Observability

| Component | Status | Evidence |
|-----------|--------|----------|
| Prometheus metrics | DONE | `backend/app/infra/metrics.py`, `/metrics` endpoint |
| SLO recording rules | DONE | `prometheus/rules/slo_recording.yml` |
| Burn-rate alerts | DONE | `prometheus/rules/slo_alerts.yml` |
| Canary alerts | DONE | `prometheus/rules/canary_alerts.yml` |
| Job heartbeat alerts | DONE | `prometheus/rules/jobs_outbox_alerts.yml` |
| Break-glass alerts | DONE | `prometheus/rules/break_glass_alerts.yml` |
| Admin auth alerts | DONE | `prometheus/rules/admin_auth_alerts.yml` |
| Org abuse alerts | DONE | `prometheus/rules/org_abuse_alerts.yml` |
| Grafana dashboards | DONE | `observability/grafana/` |
| Loki log aggregation | DONE | `observability/loki/` |
| Tempo distributed tracing | DONE | `observability/tempo/` |

### DR Readiness

| Capability | Status | Evidence |
|-----------|--------|----------|
| WAL archiving | DONE | `docs/DISASTER_RECOVERY.md` |
| PITR restore script | DONE | `ops/pitr_restore.sh` |
| PITR drill automation | DONE | `ops/pitr_restore_drill.sh` |
| Backup verification | DONE | `ops/backup_verify.sh` |
| Base backup script | DONE | `ops/backup_basebackup.sh` |
| RPO target | DONE | "Minutes" per DR doc |
| RTO target | DONE | "30 minutes" per DR doc |
| Drill reports | DONE | `ops/drill-reports/` |

### Test Portfolio Health

| Category | Count | Evidence |
|----------|-------|----------|
| Backend test files | 239 | `backend/tests/test_*.py` |
| E2E spec files | 9 | `web/e2e/tests/*.spec.ts` |
| Web unit tests | 7 | `web/tests/*.test.ts` |
| Smoke tests | 2 | `backend/tests/smoke/` |
| RLS isolation tests | DONE | `backend/tests/test_postgres_rls.py` |
| Org scope regression suite | DONE | `backend/tests/test_org_scope_regression_suite.py` |
| Cross-org isolation tests | DONE | `backend/tests/test_org_isolation_regressions.py` |

---

## 6. Security & Governance

### Controls Inventory

| Control | Maturity | Evidence |
|---------|----------|----------|
| **Authentication** | High | SaaS identity + admin proxy auth + basic auth fallback |
| **Authorization (RBAC)** | High | 27 permissions, 7 roles, per-route enforcement |
| **Multi-tenancy isolation** | High | RLS + context propagation |
| **Admin access hardening** | High | Proxy auth, IP allowlist, read-only mode, break-glass |
| **MFA** | Medium | Supported but enforcement matrix unclear |
| **Audit logging** | High | Immutable admin/config/feature/integration audits |
| **Secrets management** | High | AWS Secrets Manager, env fallback, prod validation |
| **Rate limiting** | High | Per-route, per-IP limits documented |
| **WAF** | High | Cloudflare baseline documented |
| **Bot protection** | High | Captcha on public forms |
| **CORS** | High | Strict mode in prod |
| **CSRF** | High | Token validation |
| **Supply chain** | High | Pinned SHA actions, no `curl | sh`, Trivy/Grype/Gitleaks |
| **SAST** | Medium | Bandit high-severity only |
| **Container scanning** | High | Trivy + Grype CRITICAL gate |
| **SBOM** | High | Syft SPDX-JSON per image |

### Audit Logging Coverage

| Audit Type | Table | Retention | Evidence |
|------------|-------|-----------|----------|
| Admin actions | `admin_audit_logs` | 3 years | `docs/ADMIN_ACTION_AUDIT.md` |
| Config changes | `config_audit_logs` | 7 years | `backend/app/domain/config_audit/` |
| Feature flags | `feature_flag_audit_logs` | 7 years | `docs/FEATURE_FLAG_GOVERNANCE.md` |
| Integrations | `integration_audit_logs` | 7 years | `backend/app/domain/integration_audit/` |
| Break-glass sessions | Embedded in admin audit | 3 years | `docs/BREAK_GLASS.md` |

### Access Review Readiness

| Capability | Status | Evidence |
|-----------|--------|----------|
| Access review snapshots | DONE | `backend/scripts/access_review_snapshot.py` |
| Access review reports | DONE | `backend/scripts/access_review_report.py` |
| Break-glass review workflow | DONE | POST `/v1/admin/break-glass/{session_id}/review` |

### Supply Chain Posture

| Check | Status | Evidence |
|-------|--------|----------|
| Pinned GitHub Action SHAs | DONE | All actions use commit SHA pins |
| No `curl \| sh` | DONE | `docs/CI_SUPPLY_CHAIN.md` |
| Trivy image scanning | DONE | CRITICAL gate |
| Grype image scanning | DONE | CRITICAL gate |
| Gitleaks secrets scanning | DONE | Pre-commit + CI |
| SBOM generation | DONE | Syft for api/web images |
| Dependency review | Partial | No Dependabot alerts visible |

---

## 7. Roadmap (P0/P1/P2)

### P0: Must-Fix to Launch Safely (1-2 weeks)

| Item | Why | Evidence | Scope | Owner | Effort | Acceptance Criteria | Verification |
|------|-----|----------|-------|-------|--------|---------------------|--------------|
| **Extend RLS to `client_users`** | Critical isolation gap for client PII | `audit_rls_coverage.py` shows missing | Add migration + policy | Backend | S | Policy exists, CI passes | `python scripts/audit_rls_coverage.py --fail-on-core-missing` |
| **Extend RLS to `notifications_center`** | Notification leak risk | Same | Add migration + policy | Backend | S | Same | Same |
| **Extend RLS to `checklists`** | Checklist data isolation | Same | Add migration + policy | Backend | S | Same | Same |
| **Document MFA enforcement matrix** | Compliance evidence gap | `docs/BREAK_GLASS.md` unclear | Update docs + add test | Security | S | Matrix in SECURITY_MODEL.md | Manual review |
| **Add E2E test for invoice payment** | High-risk untested flow | Missing in `web/e2e/tests/` | New spec file | QA | M | Spec passes in CI | `npx playwright test invoices` |

### P1: Enterprise Hardening (1-2 months)

| Item | Why | Evidence | Scope | Owner | Effort | Acceptance Criteria | Verification |
|------|-----|----------|-------|-------|--------|---------------------|--------------|
| **Feature flag percentage rollout** | Safer deployments | `service.py` boolean-only | Add percentage + cohort logic | Backend | M | 10/25/50/100% options | Test with org subset |
| **Module API contracts ADR** | Platform evolution safety | No formal contracts | Write ADR + lint rule | Architecture | S | ADR merged, CI check | PR review |
| **Extend RLS to all org-scoped tables** | Complete isolation | ~20 tables total | Migration per table | Backend | M | All tables covered | RLS audit script |
| **Add subscription E2E tests** | Recurring revenue risk | Missing flow | New spec file | QA | M | Spec passes | `npx playwright test` |
| **Add data rights E2E test** | GDPR compliance | Missing flow | New spec file | QA | M | Spec passes | `npx playwright test` |
| **Break-glass MFA enforcement test** | Security validation | Untested | Add test case | Security | S | Test passes | `pytest test_break_glass.py` |
| **Dependabot/Renovate setup** | Dependency freshness | No automated updates | Configure + PR workflow | DevOps | S | PRs created weekly | GitHub settings |

### P2: Platform Expansion (3-12 months)

| Item | Why | Evidence | Scope | Owner | Effort | Acceptance Criteria | Verification |
|------|-----|----------|-------|-------|--------|---------------------|--------------|
| **Second vertical abstraction** | Market expansion | Current cleaning-specific | Extract interfaces | Architecture | L | Generic `ServiceBooking` type | Compile check |
| **Franchise hierarchy** | B2B growth | No parent-child | `org_parent_id` column | Backend | M | Franchisor can see franchisees | API test |
| **White-label branding** | Enterprise sales | No theming | `org_branding` table | Frontend | M | Logo/color per org | Visual check |
| **Custom domain support** | White-label premium | No domain routing | Caddy dynamic TLS | DevOps | L | Custom domain resolves | curl test |
| **A/B testing framework** | Product optimization | No experimentation | Extend feature flags | Backend | L | Cohort assignment works | Analytics |
| **SOC 2 readiness review** | Enterprise compliance | Controls exist, no audit | Engage auditor | Compliance | L | Report issued | Auditor sign-off |

---

## 8. Appendix

### Commands Executed

```bash
# Documentation inventory
find . -name "*.md" -path "*/docs/*" | wc -l  # 155 docs

# Test inventory
ls backend/tests/test_*.py | wc -l  # 239 test files
find web/e2e -name "*.spec.ts" | wc -l  # 9 E2E specs

# Domain module count
ls backend/app/domain/ | grep -v __pycache__ | wc -l  # 61 modules

# Migration count
ls backend/alembic/versions/*.py | wc -l  # 153 migrations

# Runbook count
ls docs/runbooks/*.md | wc -l  # 20 runbooks
```

### Key Files Referenced

| Category | Key Files |
|----------|-----------|
| **Security** | `backend/SECURITY_MODEL.md`, `docs/SECRETS_BACKEND.md`, `docs/SECURITY_WAF_BASELINE.md`, `docs/SECURITY_RATE_LIMITS.md` |
| **Multi-tenancy** | `backend/alembic/versions/0044_postgres_rls_org_isolation.py`, `backend/app/infra/org_context.py`, `backend/app/infra/db.py`, `backend/scripts/audit_rls_coverage.py` |
| **Feature flags** | `backend/app/domain/feature_modules/service.py`, `docs/FEATURE_FLAG_GOVERNANCE.md` |
| **Auth/RBAC** | `backend/app/api/admin_auth.py`, `backend/app/domain/iam/permissions.py` |
| **Observability** | `docs/SLO.md`, `docs/OBSERVABILITY.md`, `prometheus/rules/slo_alerts.yml` |
| **CI/CD** | `.github/workflows/ci.yml`, `.github/workflows/e2e.yml` |
| **Operations** | `docs/DEPLOY_RUNBOOK.md`, `docs/ROLLBACK_RUNBOOK.md`, `docs/DISASTER_RECOVERY.md` |
| **Audit** | `docs/ADMIN_ACTION_AUDIT.md`, `docs/AUDIT_RETENTION_POLICY.md` |
| **Break-glass** | `docs/BREAK_GLASS.md`, `backend/app/api/break_glass.py`, `backend/app/api/admin_safety.py` |

### NOT VERIFIED Items

| Item | Verification Command |
|------|---------------------|
| Actual RLS policy enforcement at runtime | `SET LOCAL app.current_org_id = '<uuid>'; SELECT * FROM leads;` |
| MFA enforcement in break-glass flow | Manual test with MFA-required role |
| Alertmanager webhook delivery | Trigger SLO breach in staging |
| PITR restore drill success | Run `ops/pitr_restore_drill.sh` in staging |
| k6 performance baseline | Set `PERF_BASE_URL` and run CI job |

---

**Report Generated:** 2026-01-30
**Next Review:** 2026-03-01 (recommended quarterly)
