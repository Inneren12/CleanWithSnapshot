# Disaster Recovery (DR) Runbook

This runbook documents the disaster recovery procedures for CleanWithSnapshot, including both
traditional backup restore and Point-in-Time Recovery (PITR) using WAL archiving.

## Objectives

| Environment | Recovery Time Objective (RTO) | Recovery Point Objective (RPO) | Method |
| --- | --- | --- | --- |
| Staging (drill) | **90 minutes** | **24 hours** | Daily backup restore |
| Production (daily backup) | **4 hours** | **24 hours** | pg_dump restore |
| Production (PITR) | **2 hours** | **5 minutes** | WAL archive restore |

**RTO** = time to restore service to healthy `/readyz` status.
**RPO** = maximum tolerable data loss based on last successful backup/WAL sync.

## Backup Artifacts

### Traditional Backups (Phase 0)

- **Postgres dumps**: `/opt/backups/postgres/cleaning_YYYYMMDDTHHMMSSZ.sql.gz`
- **Uploads archives**: `/opt/backups/postgres/uploads_YYYYMMDDTHHMMSSZ.tar.gz`
- **Backup heartbeat**: `/opt/backups/postgres/LAST_SUCCESS.txt` (used by `/healthz/backup`)

Generated via `ops/backup_now.sh` and validated with `ops/backup_verify.sh`.

### PITR Backups (WAL Archiving)

- **Base backups**: `/opt/backups/postgres/basebackup_YYYYMMDDTHHMMSSZ.tar.gz`
- **WAL archives**: `/opt/backups/postgres/wal_archive_YYYYMMDDTHHMMSSZ.tar.gz`
- **Live WAL archive**: Docker volume `pg_wal_archive` (sync offsite every 5 min)
- **Base backup heartbeat**: `/opt/backups/postgres/LAST_BASEBACKUP.txt`
- **WAL sync heartbeat**: `ops/state/wal_sync_last_ok.txt`

Generated via `ops/backup_basebackup.sh` and synced via `ops/wal_archive_sync.sh`.

## Staging Restore (Step-by-Step)

> This is the required DR drill. Run at least quarterly and record the result in the DR drill record
> template below.

### 1) Copy the latest backup artifacts to staging

```bash
# From production host
scp /opt/backups/postgres/cleaning_YYYYMMDDTHHMMSSZ.sql.gz \
  staging:/opt/backups/postgres/

scp /opt/backups/postgres/uploads_YYYYMMDDTHHMMSSZ.tar.gz \
  staging:/opt/backups/postgres/

scp /opt/backups/postgres/LAST_SUCCESS.txt \
  staging:/opt/backups/postgres/
```

### 2) Run the staging restore script

```bash
cd /opt/cleaning

TARGET_ENV=staging \
CONFIRM_STAGING_RESTORE=YES \
BACKUP_FILE=/opt/backups/postgres/cleaning_YYYYMMDDTHHMMSSZ.sql.gz \
UPLOADS_ARCHIVE=/opt/backups/postgres/uploads_YYYYMMDDTHHMMSSZ.tar.gz \
./ops/restore_to_staging.sh
```

**Optional:** if your staging `.env` lives elsewhere, pass `ENV_FILE=/path/to/staging.env`.

### 3) Run post-restore validations

```bash
# API checks
curl -fsS http://localhost:8000/healthz | jq .
curl -fsS http://localhost:8000/readyz | jq .

# Backup health marker (optional if API mounted to /opt/backups/postgres)
curl -fsS http://localhost:8000/healthz/backup | jq .

# Sample queries
# (Use counts/IDs that are stable and representative for your data set.)
docker compose exec -T db psql -U postgres -d cleaning -c "SELECT COUNT(*) FROM bookings;"
docker compose exec -T db psql -U postgres -d cleaning -c "SELECT COUNT(*) FROM leads;"
```

### 4) Record the drill

Complete the DR drill record template below, including timestamps and any deviations.

## Validation Checklist (Staging)

- [ ] `/healthz` returns HTTP 200 with status `ok`.
- [ ] `/readyz` returns HTTP 200 with `database.migrations_current=true`.
- [ ] `/healthz/backup` returns HTTP 200 and shows a recent `LAST_SUCCESS.txt` timestamp.
- [ ] Sample queries return expected counts (bookings, leads, clients, invoices).
- [ ] Uploads directory restored (spot-check an image/file in `var/uploads`).
- [ ] Jobs heartbeat shows `ok=true` (if `JOBS_ENABLED=true`).

## DR Drill Record Template

```
Date (UTC):
Primary operator:
Secondary reviewer:
Environment: staging
Backup file:
Uploads archive:
Start time (UTC):
End time (UTC):
Duration (minutes):
RTO target (minutes):
RTO achieved (minutes):
RPO target (hours):
RPO achieved (hours):
Steps followed:
  - Copy backups
  - Run restore script
  - Run validations
Validation results:
  - /healthz:
  - /readyz:
  - /healthz/backup:
  - Sample queries:
  - Uploads check:
Issues encountered:
Follow-up actions:
```

## Point-in-Time Recovery (PITR)

PITR enables recovery to any specific point in time after a base backup, using WAL archives.
This significantly reduces RPO from 24 hours (daily backup) to 5 minutes (WAL sync interval).

### Prerequisites

1. **WAL archiving enabled** (configured in docker-compose.yml)
2. **Base backup available** (from `ops/backup_basebackup.sh`)
3. **WAL archives synced offsite** (from `ops/wal_archive_sync.sh`)

### PITR Restore Procedure

#### 1) Identify the target recovery time

Determine the point in time you want to recover to. This must be after the base backup timestamp.

```bash
# Check available base backups
ls -la /opt/backups/postgres/basebackup_*.tar.gz

# Check WAL archive coverage
ls -la /opt/backups/postgres/wal_archive_*.tar.gz
```

#### 2) Run the PITR restore script

```bash
cd /opt/cleaning

TARGET_TIME="2026-01-25 14:30:00 UTC" \
BASE_BACKUP=/opt/backups/postgres/basebackup_20260125T120000Z.tar.gz \
WAL_ARCHIVE=/opt/backups/postgres/wal_archive_20260125T120000Z.tar.gz \
CONFIRM_PITR_RESTORE=YES \
./ops/pitr_restore.sh
```

**Environment variables:**
- `TARGET_TIME`: Exact recovery target (e.g., "2026-01-25 14:30:00 UTC")
- `BASE_BACKUP`: Path to base backup tarball
- `WAL_ARCHIVE`: Path to WAL archive tarball (optional if using live volume)
- `CONFIRM_PITR_RESTORE=YES`: Safety confirmation (required)

**Alternative recovery targets:**
```bash
# Recover to end of base backup (no WAL replay)
RECOVERY_TARGET=immediate ...

# Recover to latest available WAL (apply all archives)
RECOVERY_TARGET=latest ...
```

#### 3) Verify the recovery

```bash
# Health checks
curl -fsS http://localhost:8000/healthz | jq .
curl -fsS http://localhost:8000/readyz | jq .

# Verify data as of target time
docker compose exec -T db psql -U postgres -d cleaning -c \
  "SELECT MAX(created_at) FROM bookings;"
```

### PITR Backup Schedule

**Recommended cron entries:**

```bash
# Daily base backup at 2 AM
0 2 * * * /opt/cleaning/ops/backup_basebackup.sh

# WAL archive sync every 5 minutes
*/5 * * * * WAL_SYNC_TARGET="s3://mybucket/wal-archive/" /opt/cleaning/ops/wal_archive_sync.sh

# Traditional backup (kept for compatibility)
0 3 * * * /opt/cleaning/ops/backup_now.sh
```

### PITR Monitoring

Monitor these heartbeat files to ensure PITR capability:

| File | Maximum Age | Alert Condition |
| --- | --- | --- |
| `/opt/backups/postgres/LAST_BASEBACKUP.txt` | 26 hours | Base backup stale |
| `ops/state/wal_sync_last_ok.txt` | 10 minutes | WAL sync failing |

### PITR DR Drill Record Template

```
Date (UTC):
Primary operator:
Secondary reviewer:
Environment: staging
Recovery target type: time / immediate / latest
Target time (if applicable):
Base backup file:
WAL archive file:
Start time (UTC):
End time (UTC):
Duration (minutes):
RTO target (minutes): 120
RTO achieved (minutes):
RPO target (minutes): 5
RPO achieved (minutes):
Verification results:
  - /healthz:
  - /readyz:
  - Data timestamp check:
Issues encountered:
Follow-up actions:
```

---

## Automated PITR Restore Drill (Staging)

The automated PITR restore drill script (`ops/pitr_restore_drill.sh`) provides a fully automated way to
validate PITR capability on staging environments. It performs all steps of a PITR restore and generates
a detailed report.

### Quick Start

```bash
# Full automated drill (creates backup, restores, verifies)
cd /opt/cleaning
TARGET_ENV=staging CONFIRM_DRILL=YES ./ops/pitr_restore_drill.sh
```

### What the Drill Does

1. **Pre-drill health check** - Captures current API/DB health status
2. **Insert marker record** - Creates a test record to verify PITR recovery point
3. **Create base backup** - Runs `backup_basebackup.sh` (or uses existing)
4. **Perform PITR restore** - Restores to target timestamp using WAL
5. **Wait for services** - Monitors service stabilization
6. **Post-restore health checks** - Validates `/healthz` and `/readyz`
7. **Data integrity verification** - Compares record counts, checks marker
8. **Run smoke tests** - Executes `smoke.sh` for end-to-end validation
9. **Generate report** - Creates markdown report in `ops/drill-reports/`

### Usage Options

```bash
# Full automated drill (recommended for quarterly drills)
TARGET_ENV=staging \
CONFIRM_DRILL=YES \
./ops/pitr_restore_drill.sh

# Drill with specific backup files
TARGET_ENV=staging \
CONFIRM_DRILL=YES \
BASE_BACKUP=/opt/backups/postgres/basebackup_20260125T120000Z.tar.gz \
WAL_ARCHIVE=/opt/backups/postgres/wal_archive_20260125T120000Z.tar.gz \
TARGET_TIME="2026-01-25 14:30:00 UTC" \
./ops/pitr_restore_drill.sh

# Skip backup creation (use most recent existing backup)
TARGET_ENV=staging \
CONFIRM_DRILL=YES \
SKIP_BACKUP=true \
./ops/pitr_restore_drill.sh
```

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `TARGET_ENV` | Yes | - | Must be "staging" (safety check) |
| `CONFIRM_DRILL` | Yes | - | Must be "YES" to proceed |
| `BASE_BACKUP` | No | auto | Path to base backup tarball |
| `WAL_ARCHIVE` | No | auto | Path to WAL archive tarball |
| `TARGET_TIME` | No | 1 min ago | Recovery target time |
| `ENV_FILE` | No | `.env` | Path to environment file |
| `API_BASE_URL` | No | `http://localhost:8000` | API endpoint for health checks |
| `SKIP_BACKUP` | No | `false` | Skip creating fresh backup |
| `DRILL_REPORT_DIR` | No | `ops/drill-reports` | Report output directory |

### Safety Guards

The drill script includes multiple safety checks to prevent accidental production impact:

1. **Environment check**: `TARGET_ENV` must be explicitly set to "staging"
2. **Confirmation required**: `CONFIRM_DRILL=YES` must be set
3. **Production detection**: Refuses to run if `.env` contains `APP_ENV=prod`
4. **Pre-restore backup**: Current data is backed up before restore

### Post-Drill Verification

Run the standalone verification script to validate the restore:

```bash
./ops/pitr_verify.sh
```

This checks:
- Docker services running (db, api, web, jobs)
- PostgreSQL recovery status (not in recovery mode)
- WAL archiving enabled
- `/healthz` endpoint (status, db_connected)
- `/readyz` endpoint (status, migrations_current)
- Database queries (record counts, data timestamps)

### Drill Reports

Reports are saved to `ops/drill-reports/` with the naming convention:
`pitr_drill_YYYYMMDDTHHMMSSZ.md`

Each report includes:
- Configuration parameters
- Step-by-step execution log
- Pre/post health check results
- Data integrity verification
- RTO measurement
- Pass/fail summary
- Troubleshooting guidance (if failed)

### Recommended Drill Schedule

| Frequency | Type | Purpose |
|-----------|------|---------|
| Quarterly | Full automated drill | Validate PITR capability |
| After infrastructure changes | Targeted drill | Verify backup/restore still works |
| After PostgreSQL upgrades | Full drill | Confirm compatibility |

### CI/CD Integration

For automated scheduled drills, add to your CI pipeline:

```yaml
# Example: GitHub Actions scheduled PITR drill
pitr-drill:
  runs-on: ubuntu-latest
  environment: staging
  schedule:
    - cron: '0 3 1 */3 *'  # Quarterly on the 1st at 3 AM
  steps:
    - uses: actions/checkout@v4
    - name: Run PITR drill
      run: |
        TARGET_ENV=staging \
        CONFIRM_DRILL=YES \
        API_BASE_URL=${{ secrets.STAGING_API_URL }} \
        ./ops/pitr_restore_drill.sh
    - name: Upload drill report
      uses: actions/upload-artifact@v4
      with:
        name: pitr-drill-report
        path: ops/drill-reports/*.md
```

---

## Notes & Escalation

- If `/readyz` returns non-200 after restore, run `docker compose exec -T api alembic upgrade head`
  and re-check readiness.
- Escalate any RTO/RPO misses to the incident log and update this runbook with corrections.
- For PITR failures, check PostgreSQL logs: `docker compose logs db`
- If PITR restore fails, the pre-restore data is preserved at `pg_data.pre_pitr_*`
