# Release Checklist

This document provides a streamlined, actionable checklist for releasing CleanWithSnapshot. For comprehensive deployment readiness, also refer to [GO_NO_GO.md](./GO_NO_GO.md).

## Pre-Release Verification

### 1. CI/CD Gates ✅

All CI checks must pass before merging to main:

- [ ] **API Lint** - `ruff check` passes without errors
- [ ] **API Unit Tests** - All unit tests pass (excluding smoke/postgres)
- [ ] **API Prod Config** - Production configuration validates successfully
- [ ] **Web Typecheck** - TypeScript compilation succeeds (`tsc --noEmit`)
- [ ] **Web Build** - Next.js build completes without errors
- [ ] **Infrastructure Validation** - docker-compose.yml validates and bash scripts have valid syntax

**Verify:** Check GitHub Actions status on your PR before merging.

```bash
# View CI status for current branch
gh pr checks
```

### 2. Local Testing

- [ ] **Local smoke tests pass**
  ```bash
  # Set environment for local testing
  export API_BASE_URL="http://localhost:8000"
  export WEB_BASE_URL="http://localhost:3000"
  export ADMIN_USER="admin"
  export ADMIN_PASS="your-local-admin-password"
  export SMOKE_SKIP_BACKUP="true"

  # Run smoke test pack
  ./scripts/smoke.sh
  ```

- [ ] **Readiness check passes locally**
  ```bash
  curl -fsS http://localhost:8000/readyz | jq .
  # Verify: {"ok": true, "checks": [...all ok: true]}
  ```

- [ ] **Manual testing complete**
  - [ ] Create a lead via web UI
  - [ ] Generate an estimate
  - [ ] View admin dashboard
  - [ ] Test critical user flows

### 3. Database & Migrations

- [ ] **Migrations are current**
  ```bash
  # Check current revision matches head
  docker compose exec api alembic current
  docker compose exec api alembic heads
  ```

- [ ] **Migration tested on staging/dev database**
  ```bash
  # Test migration on non-production first
  docker compose exec api alembic upgrade head
  ```

- [ ] **Rollback plan prepared** (if migration introduces breaking changes)
  ```bash
  # Document the downgrade command for this release
  # alembic downgrade <previous_revision>
  ```

### 4. Configuration Review

- [ ] **Environment variables validated**
  - [ ] No default/placeholder secrets in production `.env`
  - [ ] Strong passwords configured (12+ chars, not `change-me`, `secret`, etc.)
  - [ ] `APP_ENV=prod` set
  - [ ] `STRICT_CORS=true` with explicit origins
  - [ ] Required secrets present: `AUTH_SECRET_KEY`, portal secrets, Stripe keys

- [ ] **Production config validation passes**
  ```bash
  # This is also checked in CI
  python -c "from app.settings import Settings; s = Settings(); print(f'✓ Config valid: APP_ENV={s.app_env}')"
  ```

### 5. Dependencies & Security

- [ ] **Dependencies up to date**
  - [ ] Review `backend/requirements.txt` for security updates
  - [ ] Review `web/package.json` for security updates
  - [ ] Run `npm audit` on web (if applicable)

- [ ] **No known vulnerabilities** in dependencies

### 6. Documentation

- [ ] **Changelog updated** (if maintaining CHANGELOG.md)
- [ ] **Breaking changes documented** (if any)
- [ ] **API documentation current** (`/docs` endpoint reflects changes)
- [ ] **Runbooks updated** if operational procedures changed

## Release Execution

### 1. Pre-Deployment

- [ ] **Announce maintenance window** (if downtime expected)
- [ ] **Tag release in git**
  ```bash
  git tag -a v1.x.x -m "Release v1.x.x: Brief description"
  git push origin v1.x.x
  ```

- [ ] **Backup production database**
  ```bash
  # Ensure backup is fresh before deployment
  ./ops/backup.sh  # or your backup procedure
  # Verify: /opt/backups/postgres/LAST_SUCCESS.txt should be recent
  ```

### 2. Deployment

Follow the [DEPLOY_RUNBOOK.md](./DEPLOY_RUNBOOK.md) for detailed steps. Quick reference:

1. **Pull latest code**
   ```bash
   cd /opt/cleaning  # or your deployment directory
   git fetch origin
   git checkout main
   git pull origin main
   ```

2. **Build images**
   ```bash
   docker compose build
   ```

3. **Run migrations**
   ```bash
   docker compose up -d db
   sleep 5  # Wait for DB to be ready
   docker compose exec api alembic upgrade head
   ```

4. **Restart services**
   ```bash
   docker compose up -d
   ```

### 3. Post-Deployment Verification

**Critical checks within 5 minutes of deployment:**

- [ ] **Health check passing**
  ```bash
  curl -fsS https://api.panidobro.com/healthz
  # Expected: {"status":"ok"}
  ```

- [ ] **Readiness check passing**
  ```bash
  curl -fsS https://api.panidobro.com/readyz | jq .
  # Expected: {"ok": true, "checks": [...all ok: true]}
  # If jobs enabled, verify heartbeat is fresh
  ```

- [ ] **Smoke tests pass**
  ```bash
  export API_BASE_URL="https://api.panidobro.com"
  export WEB_BASE_URL="https://panidobro.com"
  export ADMIN_USER="<prod-admin-user>"
  export ADMIN_PASS="<prod-admin-password>"
  export SMOKE_SKIP_BACKUP="false"

  ./scripts/smoke.sh
  ```

- [ ] **Services running**
  ```bash
  docker compose ps
  # All services should be "running" (not restarting)
  ```

- [ ] **No errors in logs**
  ```bash
  docker compose logs --tail=100 api web
  # Review for startup errors or exceptions
  ```

- [ ] **Job heartbeat current** (if jobs enabled)
  ```bash
  curl -fsS -u "$ADMIN_USER:$ADMIN_PASS" \
    https://api.panidobro.com/v1/admin/jobs/status | jq .
  # Verify: last_heartbeat is within JOB_HEARTBEAT_TTL_SECONDS (default 180s)
  ```

### 4. Monitoring (first 30 minutes)

- [ ] **Monitor error rates** in logs
- [ ] **Check response times** (P95 latency acceptable)
- [ ] **Verify user flows** working (lead creation, estimates, admin access)
- [ ] **Monitor metrics endpoint** (if enabled)
  ```bash
  curl -fsS -H "Authorization: Bearer $METRICS_TOKEN" \
    https://api.panidobro.com/v1/metrics | grep -E "http_requests_total|http_request_duration"
  ```

## Rollback Procedure

If critical issues arise:

1. **Verify the issue**
   ```bash
   # Check health/readiness
   curl -i https://api.panidobro.com/readyz

   # Review recent logs
   docker compose logs --tail=500 api
   ```

2. **Rollback to previous version**
   ```bash
   cd /opt/cleaning
   git fetch origin
   git checkout <previous-good-commit-sha>
   docker compose build
   docker compose up -d
   ```

3. **Rollback database** (if migrations were applied)
   ```bash
   docker compose exec api alembic downgrade <previous-revision>
   ```

4. **Verify rollback successful**
   ```bash
   ./scripts/smoke.sh
   ```

5. **Investigate and document** the failure
   - Create incident report
   - Schedule post-mortem

## Go/No-Go Decision Criteria

### 🚀 GO if ALL are true:

- ✅ All CI checks passing
- ✅ Local smoke tests pass
- ✅ Staging environment validated
- ✅ Database backup fresh
- ✅ No critical production issues currently
- ✅ Team available for monitoring post-deployment
- ✅ Rollback plan prepared

### 🛑 NO-GO if ANY are true:

- ❌ CI checks failing
- ❌ Smoke tests failing on staging
- ❌ Critical production issue ongoing
- ❌ Database migrations risky/untested
- ❌ Breaking changes without communication plan
- ❌ Team unavailable for post-deployment monitoring

## Environment-Specific Notes

### Development (`APP_ENV=dev`)
- Relaxed validation
- `X-Test-Org` header honored for multi-tenant testing
- CORS can be permissive

### Staging
- Should mirror production config
- Use test Stripe keys
- Test email mode or use dev email addresses
- Run full smoke tests before promoting to production

### Production (`APP_ENV=prod`)
- Strict validation enforced
- No default/placeholder secrets allowed
- `STRICT_CORS=true` required
- `ADMIN_MFA_REQUIRED=true` recommended
- `LEGACY_BASIC_AUTH_ENABLED=false` recommended (use SaaS auth)
- Monitoring and alerting active

## Post-Release Tasks

- [ ] **Monitor for 24 hours** for latent issues
- [ ] **Update documentation** if needed
- [ ] **Communicate release** to stakeholders
- [ ] **Close related issues/tickets**
- [ ] **Verify backups continue** post-deployment
- [ ] **Review metrics** for anomalies

## References

- **Comprehensive Go/No-Go Checklist**: [GO_NO_GO.md](./GO_NO_GO.md)
- **Deployment Procedures**: [DEPLOY_RUNBOOK.md](./DEPLOY_RUNBOOK.md)
- **Smoke Test Documentation**: [SMOKE.md](./SMOKE.md)
- **Operations Guide**: [backend/OPERATIONS.md](../backend/OPERATIONS.md)
- **Main Runbook**: [RUNBOOK.md](../RUNBOOK.md)

---

**Last Updated**: 2026-01-06
**Version**: 1.0
