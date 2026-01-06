# Deployment Runbook

This runbook provides step-by-step procedures for deploying CleanWithSnapshot to production, staging, or development environments.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Deployment Overview](#deployment-overview)
- [Standard Deployment](#standard-deployment)
- [Zero-Downtime Deployment](#zero-downtime-deployment)
- [Post-Deployment Verification](#post-deployment-verification)
- [Rollback Procedures](#rollback-procedures)
- [Troubleshooting](#troubleshooting)
- [Environment-Specific Procedures](#environment-specific-procedures)

## Prerequisites

### Required Access
- SSH access to deployment server
- Git repository access
- Docker and Docker Compose installed on target server
- Admin credentials for post-deployment verification

### Pre-Deployment Checklist
- [ ] All CI checks passing on the branch/commit to deploy
- [ ] Release checklist completed ([RELEASE_CHECKLIST.md](./RELEASE_CHECKLIST.md))
- [ ] Database backup taken and verified
- [ ] Team notified of deployment window
- [ ] Rollback plan prepared

### Required Tools
```bash
# Verify prerequisites
docker --version          # Docker Engine 20.10+
docker compose version    # Docker Compose 2.0+
git --version            # Git 2.x+
curl --version           # For health checks
jq --version             # For JSON parsing (optional but recommended)
```

## Deployment Overview

### Deployment Flow
1. **Pre-deployment**: Backup, verification, preparation
2. **Code update**: Pull latest code from git
3. **Build**: Build Docker images
4. **Database migration**: Apply schema changes
5. **Service restart**: Restart application containers
6. **Verification**: Health checks, smoke tests, monitoring
7. **Post-deployment**: Monitoring, communication, documentation

### Typical Deployment Time
- **Standard deployment**: 5-10 minutes (with brief downtime)
- **Zero-downtime deployment**: 15-20 minutes (requires blue-green setup)
- **Rollback**: 3-5 minutes

## Standard Deployment

This procedure includes a brief downtime window (typically 30-60 seconds).

### Step 1: Pre-Deployment Backup

**CRITICAL**: Always backup before deployment.

```bash
# Navigate to deployment directory
cd /opt/cleaning  # Adjust path as needed

# Create database backup
./ops/backup.sh
# OR if using Docker:
# docker compose exec db pg_dump -U postgres cleaning > /opt/backups/postgres/pre-deploy-$(date +%Y%m%d-%H%M%S).sql

# Verify backup success
ls -lh /opt/backups/postgres/
cat /opt/backups/postgres/LAST_SUCCESS.txt
```

**Expected**: Backup file created with current timestamp, LAST_SUCCESS.txt updated.

### Step 2: Pull Latest Code

```bash
# Ensure working directory is clean
git status

# Fetch and pull latest code
git fetch origin

# Deploy from main branch (or specify tag/branch)
git checkout main
git pull origin main

# OR deploy a specific tag:
# git checkout tags/v1.x.x

# Verify current commit
git log -1 --oneline
```

**Expected**: Working directory updated to target commit, no local changes.

### Step 3: Update Environment Configuration

```bash
# Review .env for any new required variables
# Compare with .env.example or .env.production.example
diff .env backend/.env.production.example

# Add any new required variables
# Edit .env with your preferred editor
nano .env  # or vim, etc.

# Validate configuration (optional but recommended)
docker compose config > /dev/null && echo "✓ docker-compose.yml valid"
```

**Expected**: `.env` file contains all required variables for the new version.

### Step 4: Build Docker Images

```bash
# Build new images (this may take 2-5 minutes)
docker compose build

# Verify images built successfully
docker images | grep cleaning

# Check image sizes (should be reasonable, typically < 1GB each)
docker images --format "table {{.Repository}}\t{{.Tag}}\t{{.Size}}" | grep cleaning
```

**Expected**: New images built without errors, reasonably sized.

### Step 5: Stop Services (Downtime Begins)

```bash
# Stop running services
docker compose down

# Verify services stopped
docker compose ps
```

**Expected**: All services stopped. **Downtime window begins here.**

### Step 6: Run Database Migrations

```bash
# Start database service only
docker compose up -d db

# Wait for database to be ready (typically 5-10 seconds)
echo "Waiting for database..."
until docker compose exec -T db pg_isready -U postgres -d cleaning >/dev/null 2>&1; do
  echo -n "."
  sleep 1
done
echo " Database ready!"

# Start API service (needed for migrations)
docker compose up -d api

# Wait for API container to be running
sleep 5

# Run migrations
echo "Running database migrations..."
docker compose exec -T api alembic upgrade head

# Verify migration success
echo "Checking migration status..."
docker compose exec -T api alembic current
docker compose exec -T api alembic heads

# Compare current with head (should match)
CURRENT=$(docker compose exec -T api alembic current | grep -oP '[a-f0-9]{12}' | head -1)
HEAD=$(docker compose exec -T api alembic heads | grep -oP '[a-f0-9]{12}' | head -1)

if [ "$CURRENT" = "$HEAD" ]; then
  echo "✓ Migrations current: $CURRENT"
else
  echo "✗ Migration mismatch! Current: $CURRENT, Head: $HEAD"
  exit 1
fi
```

**Expected**: Migrations apply successfully, current revision matches head.

### Step 7: Start All Services

```bash
# Start all services
docker compose up -d

# Wait for services to stabilize (typically 10-20 seconds)
echo "Waiting for services to start..."
sleep 15

# Check service status
docker compose ps

# Verify all services are "running" (not "restarting")
docker compose ps --format json | jq -r '.[] | "\(.Service): \(.State)"'
```

**Expected**: All services (db, api, web, caddy) in "running" state. **Downtime window ends here.**

### Step 8: Verify Deployment

See [Post-Deployment Verification](#post-deployment-verification) section below.

## Zero-Downtime Deployment

Zero-downtime deployments require a blue-green or rolling deployment strategy. This is typically implemented with:

- Load balancer (e.g., multiple Docker Compose environments with HAProxy/Nginx)
- Kubernetes or container orchestration
- Database migrations that are backwards-compatible

**Note**: The current Docker Compose setup does not support zero-downtime by default. Consider implementing blue-green deployment for production if downtime is unacceptable.

### Blue-Green Deployment Strategy (Advanced)

1. **Prepare green environment** (new version) alongside blue (current)
2. **Run migrations** that are backwards-compatible with both versions
3. **Start green environment** and verify health
4. **Switch traffic** from blue to green (via load balancer or DNS)
5. **Monitor green** environment
6. **Decommission blue** after confirming stability

## Post-Deployment Verification

**CRITICAL**: Complete these checks within 5 minutes of deployment.

### Quick Health Checks

```bash
# Set environment variables
export API_BASE_URL="https://api.panidobro.com"  # Adjust for your environment
export WEB_BASE_URL="https://panidobro.com"

# 1. API Liveness
echo "Checking API liveness..."
curl -fsS "$API_BASE_URL/healthz" | jq .
# Expected: {"status":"ok"}

# 2. API Readiness
echo "Checking API readiness..."
curl -fsS "$API_BASE_URL/readyz" | jq .
# Expected: {"ok": true, "checks": [...all ok: true]}

# 3. Web Application
echo "Checking web application..."
curl -fsS -I "$WEB_BASE_URL/" | head -1
# Expected: HTTP/2 200 or HTTP/1.1 200

# 4. Docker Services
echo "Checking Docker services..."
docker compose ps
# Expected: All services "running"
```

### Detailed Verification

```bash
# 5. Service Logs (check for errors)
echo "Reviewing recent logs..."
docker compose logs --tail=100 api web | grep -iE "error|exception|fail" || echo "No errors found"

# 6. Database Connectivity
echo "Testing database connectivity..."
docker compose exec -T db pg_isready -U postgres
# Expected: accepting connections

# 7. Migration Status
echo "Verifying migrations..."
docker compose exec -T api alembic current
# Expected: Current revision matches what you deployed

# 8. Job Heartbeat (if jobs enabled)
if [ -n "$ADMIN_USER" ] && [ -n "$ADMIN_PASS" ]; then
  echo "Checking job heartbeat..."
  curl -fsS -u "$ADMIN_USER:$ADMIN_PASS" "$API_BASE_URL/v1/admin/jobs/status" | jq .
  # Expected: Recent heartbeat (within JOB_HEARTBEAT_TTL_SECONDS, default 180s)
fi
```

### Run Smoke Tests

```bash
# Run comprehensive smoke test pack
export API_BASE_URL="https://api.panidobro.com"
export WEB_BASE_URL="https://panidobro.com"
export ADMIN_USER="<your-admin-user>"
export ADMIN_PASS="<your-admin-password>"

./scripts/smoke.sh

# Expected: All tests pass
```

### Manual Verification

- [ ] **Web UI accessible** - Navigate to homepage in browser
- [ ] **Critical user flows work**:
  - [ ] Create a lead
  - [ ] Generate an estimate
  - [ ] Admin login works
  - [ ] View dashboard
- [ ] **No console errors** in browser developer tools
- [ ] **APIs responding** - Test a few key endpoints manually

## Rollback Procedures

If critical issues are detected, follow these steps to rollback.

### Quick Rollback (Code Only)

```bash
# 1. Identify previous good commit
git log --oneline -10
# OR check your deployment log

# 2. Checkout previous commit
PREVIOUS_COMMIT="<commit-sha>"  # e.g., abc1234
git checkout $PREVIOUS_COMMIT

# 3. Rebuild images
docker compose build

# 4. Restart services
docker compose down
docker compose up -d

# 5. Verify rollback
sleep 15
curl -fsS "$API_BASE_URL/healthz"
./scripts/smoke.sh
```

### Rollback with Database Migration Downgrade

**WARNING**: Database rollbacks are risky. Only proceed if necessary and you understand the migration.

```bash
# 1. Identify the previous migration revision
# Check your deployment log or alembic history
docker compose exec api alembic history

# 2. Downgrade database
PREVIOUS_REVISION="<revision-hash>"  # e.g., abc123def456
docker compose exec api alembic downgrade $PREVIOUS_REVISION

# 3. Verify downgrade
docker compose exec api alembic current

# 4. Rollback code (as above)
git checkout $PREVIOUS_COMMIT
docker compose build
docker compose down
docker compose up -d

# 5. Verify system
./scripts/smoke.sh
```

### Emergency Rollback (Restore from Backup)

**LAST RESORT**: Use when migrations cannot be safely reversed.

```bash
# 1. Stop services
docker compose down

# 2. Restore database from backup
BACKUP_FILE="/opt/backups/postgres/pre-deploy-YYYYMMDD-HHMMSS.sql"
docker compose up -d db
sleep 10

# Drop and recreate database
docker compose exec -T db psql -U postgres <<EOF
DROP DATABASE IF EXISTS cleaning;
CREATE DATABASE cleaning;
EOF

# Restore from backup
docker compose exec -T db psql -U postgres cleaning < $BACKUP_FILE

# 3. Rollback code
git checkout $PREVIOUS_COMMIT
docker compose build

# 4. Start services WITHOUT running migrations
docker compose up -d

# 5. Verify
./scripts/smoke.sh
```

### Post-Rollback Actions

- [ ] Verify system stability
- [ ] Document what failed
- [ ] Notify team
- [ ] Schedule incident post-mortem
- [ ] Fix issues before next deployment attempt

## Troubleshooting

### Issue: Health Check Fails

```bash
# Symptom: curl $API_BASE_URL/healthz returns error or timeout

# Check service status
docker compose ps

# Check API logs
docker compose logs --tail=100 api

# Common causes:
# - Service not running (check docker compose ps)
# - Port mapping issue (check docker-compose.yml ports)
# - Firewall/network issue (check server firewall, security groups)
# - Reverse proxy misconfiguration (check Caddy logs)
```

### Issue: Readiness Check Fails

```bash
# Symptom: /readyz returns 503

# Check detailed readiness response
curl -s "$API_BASE_URL/readyz" | jq .

# Diagnose specific check failures:

# If "db" check fails:
docker compose logs db
docker compose exec db pg_isready -U postgres

# If "migrations" check fails:
docker compose exec api alembic current
docker compose exec api alembic heads
# Run: docker compose exec api alembic upgrade head

# If "jobs" check fails:
curl -u "$ADMIN_USER:$ADMIN_PASS" "$API_BASE_URL/v1/admin/jobs/status" | jq .
# Ensure job runner is running: docker compose ps jobs
# Check: docker compose logs jobs
```

### Issue: Migration Fails

```bash
# Symptom: alembic upgrade head fails with error

# Check current migration state
docker compose exec api alembic current

# View migration history
docker compose exec api alembic history

# Check database logs for errors
docker compose logs db

# Common causes:
# - Schema conflict (manual DB changes)
# - Permissions issue (check POSTGRES_USER)
# - Data incompatibility (bad migration logic)

# Resolution:
# - Review migration file in alembic/versions/
# - Consider manual intervention or rollback
# - Contact development team if migration is broken
```

### Issue: Service Keeps Restarting

```bash
# Symptom: docker compose ps shows "restarting"

# Identify which service is restarting
docker compose ps

# Check logs for the restarting service
docker compose logs <service-name>

# Common causes:
# - Configuration error (missing .env variables)
# - Dependency not ready (e.g., API waiting for DB)
# - Insufficient resources (memory, disk)
# - Port conflict

# Check resource usage
docker stats

# Check .env configuration
cat .env | grep -v "^#" | grep -v "^$"
```

### Issue: Web Build Fails

```bash
# Symptom: Web service fails to build or start

# Check web build logs
docker compose logs web

# Rebuild web image with verbose output
docker compose build --no-cache web

# Common causes:
# - Missing NEXT_PUBLIC_API_BASE_URL environment variable
# - TypeScript errors (should be caught in CI)
# - Dependency issues (npm install failures)

# Resolution:
# - Review web/package.json and web/package-lock.json
# - Ensure environment variables are set correctly
# - Check for recent breaking changes in dependencies
```

### Issue: Cannot Connect to Database

```bash
# Symptom: API logs show database connection errors

# Check database service
docker compose ps db
docker compose logs db

# Test database connectivity from host
docker compose exec -T db pg_isready -U postgres

# Test from API container
docker compose exec api python -c "
from app.infra.db import get_session_factory
import asyncio
asyncio.run(get_session_factory().__anext__())
print('✓ Database connection successful')
"

# Common causes:
# - DATABASE_URL misconfigured in .env
# - Database service not running
# - Network isolation between containers
# - PostgreSQL not accepting connections

# Check DATABASE_URL format:
# postgresql+asyncpg://user:password@host:port/database
```

## Environment-Specific Procedures

### Development Environment

```bash
# Development typically uses:
export APP_ENV="dev"
export API_BASE_URL="http://localhost:8000"
export WEB_BASE_URL="http://localhost:3000"

# Quick dev deployment (no backup needed)
git pull origin main
docker compose build
docker compose down
docker compose up -d
docker compose exec api alembic upgrade head

# Verify
curl http://localhost:8000/healthz
```

### Staging Environment

```bash
# Staging should mirror production closely
export APP_ENV="prod"  # Use prod-like config
export API_BASE_URL="https://api-staging.example.com"
export WEB_BASE_URL="https://staging.example.com"

# Follow standard deployment procedure
# Use test Stripe keys
# Run full smoke tests before promoting to production
```

### Production Environment

```bash
# Production requires all safety checks
export APP_ENV="prod"
export API_BASE_URL="https://api.panidobro.com"
export WEB_BASE_URL="https://panidobro.com"

# ALWAYS follow standard deployment procedure
# ALWAYS backup before deployment
# ALWAYS run smoke tests post-deployment
# ALWAYS monitor for at least 30 minutes post-deployment
```

## Maintenance Operations

### Restart Services (No Code Change)

```bash
# Restart all services
docker compose restart

# OR restart specific service
docker compose restart api
docker compose restart web

# Verify
docker compose ps
curl -fsS "$API_BASE_URL/healthz"
```

### Update Environment Variables Only

```bash
# Edit .env file
nano .env

# Restart services to pick up new variables
docker compose down
docker compose up -d

# Verify configuration loaded
docker compose exec api python -c "from app.settings import Settings; print(Settings())"
```

### View Logs

```bash
# Tail all logs
docker compose logs -f

# Tail specific service
docker compose logs -f api

# View last N lines
docker compose logs --tail=500 api

# Search logs for errors
docker compose logs api | grep -iE "error|exception|fail"

# Export logs to file
docker compose logs > deployment-logs-$(date +%Y%m%d-%H%M%S).log
```

### Clean Up Old Images

```bash
# Remove old Docker images to free space
docker image prune -f

# Remove all unused images, containers, volumes
docker system prune -a --volumes
# WARNING: This removes ALL unused Docker resources
```

## Post-Deployment Monitoring

Monitor these metrics for at least 30 minutes after deployment:

### 1. Service Health

```bash
# Continuous health monitoring
watch -n 30 'curl -fsS $API_BASE_URL/readyz | jq .'
```

### 2. Error Rates

```bash
# Monitor logs for errors
docker compose logs -f api | grep -iE "error|exception|fail"
```

### 3. Response Times

```bash
# Test API response time
time curl -fsS "$API_BASE_URL/v1/estimate" \
  -H "Content-Type: application/json" \
  -d '{"beds":2,"baths":1,"cleaning_type":"standard"}'
```

### 4. Resource Usage

```bash
# Monitor resource consumption
docker stats
```

### 5. User-Facing Checks

- Check web UI for any visual issues
- Test critical user flows manually
- Monitor customer support channels for issues

## Deployment Log Template

Document each deployment for audit and troubleshooting:

```
Deployment Log
--------------
Date: YYYY-MM-DD HH:MM UTC
Deployer: <your-name>
Environment: Production/Staging/Dev
Git Commit: <commit-sha>
Git Tag: <tag-if-applicable>

Pre-Deployment Checks:
- [ ] CI passing
- [ ] Backup taken
- [ ] Team notified

Deployment Steps:
- Start time: HH:MM
- Code updated: HH:MM
- Images built: HH:MM
- Migrations run: HH:MM
- Services restarted: HH:MM
- Verification complete: HH:MM
- End time: HH:MM

Verification Results:
- Health check: PASS/FAIL
- Readiness check: PASS/FAIL
- Smoke tests: PASS/FAIL
- Service status: All running

Issues/Notes:
- <any issues encountered>
- <any deviations from standard procedure>

Rollback:
- Required: YES/NO
- Reason: <if rolled back>
```

## References

- **Release Checklist**: [RELEASE_CHECKLIST.md](./RELEASE_CHECKLIST.md)
- **Go/No-Go Checklist**: [GO_NO_GO.md](./GO_NO_GO.md)
- **Smoke Tests**: [SMOKE.md](./SMOKE.md), `./scripts/smoke.sh`
- **Operations Guide**: [backend/OPERATIONS.md](../backend/OPERATIONS.md)
- **Main Runbook**: [RUNBOOK.md](../RUNBOOK.md)

---

**Last Updated**: 2026-01-06
**Version**: 1.0
