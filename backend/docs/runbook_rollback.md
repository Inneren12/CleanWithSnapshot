# Rollback runbook (production)

Use this runbook when a production deploy must be rolled back. It assumes Docker Compose–based releases and the `.env.production` file described in `docs/deploy_production.md`.

## Pre-Rollback Checklist

Before initiating a rollback:

- [ ] **Incident declared** - Document incident in incident channel
- [ ] **Backup taken** - Execute `./backend/scripts/backup_pg.sh` immediately
- [ ] **Verify backup** - Check backup file exists and has reasonable size
- [ ] **Impact assessed** - Determine if issue is application or database related
- [ ] **Forward-fix evaluated** - Confirm forward-fix is not feasible
- [ ] **Stakeholders notified** - Alert team of impending rollback

## 1) Identify rollback target

1. Locate the last known-good image tag (from CI build logs or the container registry):

   ```bash
   # Check current deployed version
   docker compose ps --format json | jq -r '.[] | select(.Service=="api") | .Image'

   # List recent tags in registry (example for Docker Hub)
   curl -s "https://hub.docker.com/v2/repositories/<org>/<repo>/tags?page_size=10" | jq -r '.results[].name'
   ```

2. Confirm the tag includes the migrations level that was previously in prod:

   ```bash
   # Check what migrations were in that version (from git)
   git show <tag>:backend/alembic/versions/ | head -20
   ```

3. Identify the database migration version that matches the rollback target:

   ```bash
   # Get current migration version
   docker compose exec -T db psql -U postgres -d cleaning -c "SELECT version_num FROM alembic_version;"
   ```

## 2) Roll back the application version

1. Point Compose to the known-good tag (example shown with an `IMAGE_TAG` override):

   ```bash
   IMAGE_TAG=2025-12-15-rc1 docker compose --env-file .env -f docker-compose.yml pull
   IMAGE_TAG=2025-12-15-rc1 docker compose --env-file .env -f docker-compose.yml up -d api jobs
   ```

2. Verify containers are running the expected hash:

   ```bash
   docker compose ps --format json | jq '.[].Image'
   docker compose exec -T api python --version  # Verify code loaded
   ```

3. Smoke test `/healthz` and `/readyz` before re-enabling traffic:

   ```bash
   # Healthz should return immediately
   curl -f https://api.panidobro.com/healthz

   # Readyz will check migrations status
   curl -f https://api.panidobro.com/readyz | jq .
   ```

## 3) Handle migrations

**Migration Rollback Strategy: Forward-Fix Preferred**

The CleanWithSnapshot application follows a **forward-only migration policy** whenever possible. Database downgrades are risky and should only be used in emergencies.

### 3.1) Assess Migration Compatibility

First, determine if the migration needs to be rolled back:

**Scenario A: Additive migrations (SAFE - No DB rollback needed)**

If the failed deploy added:
- New tables
- New nullable columns
- New indexes
- New constraints that don't affect existing data

**Action:** Keep the migration in place, only rollback the application code.

**Rationale:** The old application code will ignore new database structures. This avoids risky downgrade operations.

```bash
# Verify /readyz shows migrations_current=true even with older code
curl https://api.panidobro.com/readyz | jq '.checks[] | select(.name=="migrations")'
```

**Scenario B: Breaking migrations (REQUIRES evaluation)**

If the failed deploy:
- Dropped columns or tables
- Changed column types
- Added NOT NULL constraints
- Modified existing data

**Action:** Evaluate options in Section 3.2 below.

### 3.2) Migration Rollback Options

**Option 1: Forward-Fix (STRONGLY PREFERRED)**

Ship a forward-fix migration that corrects the issue:

1. Create a new migration that fixes the problem:

   ```bash
   # Example: Migration added wrong column, fix it
   docker compose exec -T api alembic revision -m "fix_column_name_typo"
   ```

2. Edit the migration file to correct the issue:

   ```python
   def upgrade():
       op.alter_column('bookings', 'statsu', new_column_name='status')

   def downgrade():
       op.alter_column('bookings', 'status', new_column_name='statsu')
   ```

3. Deploy the fix using normal deployment process:

   ```bash
   ./ops/deploy.sh
   ```

**Benefits:**
- ✅ Preserves data integrity
- ✅ Maintains audit trail
- ✅ Avoids dangerous downgrade operations
- ✅ Can be tested in staging first
- ✅ Standard deployment process

**Drawbacks:**
- ⏱️ Takes longer (requires new deploy)
- ⏱️ Requires writing and testing new migration

**Option 2: Database Downgrade (EMERGENCY ONLY)**

**⚠️ WARNING: Only use if forward-fix is not feasible and downtime is acceptable.**

Prerequisites before downgrading:
- [ ] **Backup verified** - Recent backup exists and checksum verified
- [ ] **Downgrade function exists** - Migration has working `downgrade()`
- [ ] **Data loss assessed** - Understand what data will be lost
- [ ] **Incident documented** - Reason for emergency downgrade recorded
- [ ] **Team approval** - Senior engineer approves downgrade

Steps to downgrade database:

1. **Verify downgrade function exists:**

   ```bash
   # Find the migration file
   docker compose exec -T api alembic current -v

   # Check it has downgrade()
   docker compose exec -T api cat alembic/versions/<revision>_*.py | grep -A 10 "def downgrade"
   ```

2. **Take immediate backup (if not already done):**

   ```bash
   ./backend/scripts/backup_pg.sh

   # Verify backup
   ls -lh ./backups/pg_cleaning_*.dump
   sha256sum -c ./backups/pg_cleaning_*.dump.sha256
   ```

3. **Stop application to prevent writes during downgrade:**

   ```bash
   docker compose stop api jobs
   ```

4. **Execute downgrade:**

   ```bash
   # Downgrade one migration (most common)
   docker compose run --rm api alembic downgrade -1

   # Or to specific version
   docker compose run --rm api alembic downgrade <target_revision>

   # Or to base (DANGEROUS - drops all schema)
   # docker compose run --rm api alembic downgrade base  # DON'T DO THIS
   ```

5. **Verify migration version:**

   ```bash
   docker compose exec -T db psql -U postgres -d cleaning -c \
     "SELECT version_num FROM alembic_version;"
   ```

6. **Start application with rolled-back code:**

   ```bash
   IMAGE_TAG=<previous-tag> docker compose up -d api jobs
   ```

7. **Re-run `/readyz` to ensure `migrations_current=true`:**

   ```bash
   curl https://api.panidobro.com/readyz | jq '.checks[] | select(.name=="migrations")'

   # Should show:
   # "migrations_current": true
   # "current_version": "<previous_revision>"
   ```

8. **Document the applied action:**
   - What migration was rolled back
   - Why forward-fix wasn't feasible
   - What data was lost (if any)
   - Plan for re-applying the change

**Option 3: Database Restore (CATASTROPHIC FAILURE)**

**⚠️ EXTREME MEASURE: Only if database is corrupted or migration cannot be reversed.**

See `docs/runbook_backup_restore.md` for full restore procedure.

Quick reference:

```bash
# Stop all services
docker compose down

# Restore from backup
POSTGRES_HOST=localhost POSTGRES_DB=cleaning POSTGRES_USER=postgres \
  POSTGRES_PASSWORD=$DB_PASSWORD \
  ./backend/scripts/restore_pg.sh ./backups/pg_cleaning_<timestamp>.dump cleaning_restored

# Rename databases (manual)
docker compose exec -T db psql -U postgres << EOF
DROP DATABASE cleaning;
ALTER DATABASE cleaning_restored RENAME TO cleaning;
EOF

# Restart services
docker compose up -d
```

### 3.3) Common Migration Rollback Scenarios

**Scenario: Migration added column but app code has bugs**

Solution: Rollback app only, keep migration
```bash
IMAGE_TAG=<previous-tag> docker compose up -d api
# Migration stays, old code ignores new column
```

**Scenario: Migration renamed column, old code breaks**

Solution: Forward-fix migration to add back old column
```python
def upgrade():
    # Add back old column name as alias
    op.add_column('bookings', sa.Column('old_name', sa.String(255)))
    op.execute("UPDATE bookings SET old_name = new_name")
```

**Scenario: Migration corrupted data**

Solution: Restore from backup + replay transactions if possible
```bash
# See runbook_backup_restore.md
./backend/scripts/restore_pg.sh <backup> <dbname>
```

**Scenario: Migration failed mid-execution**

Alembic tracks migrations atomically. If it failed, version was not updated.

```bash
# Check current version
docker compose exec -T api alembic current

# Fix the migration file or data issue
# Retry migration
docker compose exec -T api alembic upgrade head
```

## 4) Emergency disablement for exports/reports

If data leaks or performance issues involve exports or reports, immediately disable them while keeping the API online:

1. Set `EXPORT_MODE=off` in the secret store / `.env` used by production.
2. Redeploy the API with the updated environment:

   ```bash
   docker compose --env-file .env -f docker-compose.yml up -d api
   ```

3. Confirm the change took effect by hitting `/readyz` (to ensure the new container is live) and validating that export/report endpoints return 404/disabled responses.

## 5) Post-rollback validation

1. Run `/healthz` (liveness) and `/readyz` (DB + jobs + migrations) to confirm green status.
2. Check metrics scrape with the bearer token:

   ```bash
   curl -H "Authorization: Bearer $METRICS_TOKEN" https://api.example.com/metrics | head
   ```

3. Verify recent logs for errors in `api` and `jobs` containers:

   ```bash
   docker compose logs --since=10m api jobs | tail -n 200
   ```

4. Announce rollback completion in the incident channel and create a follow-up ticket for the forward-fix.
