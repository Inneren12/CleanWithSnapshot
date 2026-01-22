# Disaster Recovery (DR) Runbook

This runbook documents the Phase 0 disaster recovery procedure and the staging restore drill for
CleanWithSnapshot. It is designed for **measurable** RTO/RPO outcomes and uses existing backup
artifacts (no new database technology or PITR in Phase 0).

## Objectives (Phase 0)

| Environment | Recovery Time Objective (RTO) | Recovery Point Objective (RPO) | Notes |
| --- | --- | --- | --- |
| Staging (drill) | **90 minutes** | **24 hours** | Restore latest daily backup + uploads archive. |
| Production | **4 hours** | **24 hours** | Manual restore from latest backup; no PITR. |

**RTO** = time to restore service to healthy `/readyz` status.  
**RPO** = maximum tolerable data loss based on last successful backup.

## Backup Artifacts (Phase 0)

- **Postgres dumps**: `/opt/backups/postgres/cleaning_YYYYMMDDTHHMMSSZ.sql.gz`
- **Uploads archives**: `/opt/backups/postgres/uploads_YYYYMMDDTHHMMSSZ.tar.gz`
- **Backup heartbeat**: `/opt/backups/postgres/LAST_SUCCESS.txt` (used by `/healthz/backup`)

The backup files are generated via `ops/backup_now.sh` and validated with `ops/backup_verify.sh`.

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

## Notes & Escalation

- If `/readyz` returns non-200 after restore, run `docker compose exec -T api alembic upgrade head`
  and re-check readiness.
- Escalate any RTO/RPO misses to the incident log and update this runbook with corrections.
