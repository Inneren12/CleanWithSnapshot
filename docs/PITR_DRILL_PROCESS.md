# Quarterly PITR Drill Process

This document defines the operational process for conducting quarterly Point-in-Time Recovery (PITR) drills. The goal is to validate disaster recovery capability and ensure the team maintains operational readiness for database recovery scenarios.

---

## Table of Contents

1. [Overview](#overview)
2. [Scheduling Guidance](#scheduling-guidance)
3. [Roles and Responsibilities](#roles-and-responsibilities)
4. [Pre-Drill Preparation](#pre-drill-preparation)
5. [Drill Execution](#drill-execution)
6. [Validation Steps](#validation-steps)
7. [Success Criteria](#success-criteria)
8. [Reporting Format](#reporting-format)
9. [Post-Drill Activities](#post-drill-activities)
10. [Escalation Procedures](#escalation-procedures)

---

## Overview

### Purpose

Quarterly PITR drills validate that:

- Base backups and WAL archives are being created correctly
- PITR restore procedures work as documented
- The team can execute recovery within RTO targets
- Documentation and tooling remain current

### Recovery Targets

| Metric | Target | Description |
|--------|--------|-------------|
| **RTO (Recovery Time Objective)** | 90 minutes | Time from drill start to healthy `/readyz` status |
| **RPO (Recovery Point Objective)** | 5 minutes | Maximum data loss (based on WAL sync interval) |

### Scope

Drills are conducted on **staging environments only**. Production PITR capability is validated indirectly by:

1. Confirming staging restores use the same scripts/procedures as production
2. Verifying backup artifacts are being created on production systems
3. Testing WAL archive integrity from production backups

---

## Scheduling Guidance

### Quarterly Cadence

Conduct PITR drills **once per quarter** at minimum. Recommended schedule:

| Quarter | Recommended Window | Notes |
|---------|-------------------|-------|
| Q1 | Week of January 15 | Post-holiday, before Q1 close |
| Q2 | Week of April 15 | Mid-quarter, low activity period |
| Q3 | Week of July 15 | Mid-summer, typically lower traffic |
| Q4 | Week of October 15 | Before holiday freeze period |

### Additional Drill Triggers

Run unscheduled drills after:

- PostgreSQL version upgrades
- Changes to backup scripts (`ops/backup_*.sh`, `ops/pitr_*.sh`)
- Changes to WAL archiving configuration
- Infrastructure migrations (new hosts, storage changes)
- Any backup or WAL sync alert that was resolved

### Timing Recommendations

- **Day of week:** Tuesday–Thursday (avoid Monday catch-up, Friday risk)
- **Time of day:** Business hours (09:00–16:00 local) for team availability
- **Duration:** Block 2 hours for the drill (target: complete in 90 minutes)
- **Staging impact:** Expect 15–30 minutes of staging downtime during restore

### Calendar Integration

1. Create recurring calendar events for quarterly drills
2. Include drill runbook link in calendar invite
3. Send reminder 1 week before scheduled drill
4. Confirm staging availability 24 hours before drill

---

## Roles and Responsibilities

### Required Participants

| Role | Responsibility | Required |
|------|----------------|----------|
| **Primary Operator** | Execute drill steps, run commands, document results | Yes |
| **Secondary Reviewer** | Observe, validate steps, catch errors, assist if needed | Yes |
| **Escalation Contact** | Available for consultation if issues arise | On-call |

### Role Assignments

- Rotate primary/secondary roles each quarter to cross-train team members
- Both participants should have staging access and familiarity with procedures
- Document role assignments in drill report

### Preparation Responsibilities

**Primary Operator (1 week before):**
- [ ] Confirm staging environment is available
- [ ] Verify backup scripts are current on staging
- [ ] Check that recent base backup exists
- [ ] Ensure WAL sync heartbeat is healthy

**Secondary Reviewer (day before):**
- [ ] Review drill procedures
- [ ] Confirm access to staging systems
- [ ] Prepare to document observations

---

## Pre-Drill Preparation

### 7 Days Before

- [ ] **Schedule confirmed:** Drill date/time on team calendar
- [ ] **Participants identified:** Primary operator and secondary reviewer assigned
- [ ] **Staging reserved:** No conflicting deployments or tests scheduled

### 1 Day Before

- [ ] **Backup health verified:**
  ```bash
  # Check base backup age (should be < 26 hours)
  cat /opt/backups/postgres/LAST_BASEBACKUP.txt

  # Check WAL sync heartbeat (should be < 10 minutes)
  cat ops/state/wal_sync_last_ok.txt
  ```

- [ ] **Staging health verified:**
  ```bash
  curl -fsS http://staging:8000/healthz | jq .
  curl -fsS http://staging:8000/readyz | jq .
  ```

- [ ] **Disk space sufficient:**
  ```bash
  df -h /opt/backups/postgres
  # Need at least 2x base backup size for restore
  ```

- [ ] **Documentation current:**
  - Review this process document
  - Have `docs/DISASTER_RECOVERY.md` accessible
  - Confirm `ops/pitr_restore_drill.sh` is up to date

### Day of Drill (Before Start)

- [ ] **Communication sent:** Notify team that drill is starting
- [ ] **Staging idle:** Confirm no active deployments or tests
- [ ] **Session recorded:** Start terminal recording or logging
- [ ] **Clock synced:** Note start time in UTC

---

## Drill Execution

### Automated Drill (Recommended)

Use the automated drill script for consistent execution:

```bash
cd /opt/cleaning

# Full automated drill
TARGET_ENV=staging \
CONFIRM_DRILL=YES \
./ops/pitr_restore_drill.sh
```

The script executes 10 steps automatically and generates a report.

### Manual Drill Steps

If running manually (or for understanding), follow these steps:

#### Step 1: Pre-Drill Health Check

```bash
# Record current health status
curl -fsS http://staging:8000/healthz | tee /tmp/healthz_pre.json | jq .
curl -fsS http://staging:8000/readyz | tee /tmp/readyz_pre.json | jq .
```

**Expected:** Both endpoints return HTTP 200 with healthy status.

#### Step 2: Record Current Data State

```bash
# Record row counts for comparison
docker compose exec -T db psql -U postgres -d cleaning -c \
  "SELECT 'bookings' as tbl, COUNT(*) FROM bookings
   UNION ALL SELECT 'leads', COUNT(*) FROM leads
   UNION ALL SELECT 'client_users', COUNT(*) FROM client_users;"
```

#### Step 3: Insert Drill Marker (Optional)

```bash
# Insert marker to verify PITR recovery point
docker compose exec -T db psql -U postgres -d cleaning -c "
  CREATE TABLE IF NOT EXISTS _pitr_drill_markers (
    id TEXT PRIMARY KEY,
    created_at TIMESTAMPTZ DEFAULT NOW()
  );
  INSERT INTO _pitr_drill_markers (id) VALUES ('drill_$(date +%Y%m%d%H%M%S)');
"
```

#### Step 4: Create Base Backup (If Needed)

```bash
# Skip if using existing backup
./ops/backup_basebackup.sh

# Identify backup files
BASE_BACKUP=$(ls -t /opt/backups/postgres/basebackup_*.tar.gz | head -1)
WAL_ARCHIVE=$(ls -t /opt/backups/postgres/wal_archive_*.tar.gz | head -1)
echo "Using: $BASE_BACKUP, $WAL_ARCHIVE"
```

#### Step 5: Determine Recovery Target

```bash
# Recover to 1 minute ago (before marker insertion)
TARGET_TIME=$(date -u -d "1 minute ago" '+%Y-%m-%d %H:%M:%S UTC')
echo "Recovery target: $TARGET_TIME"
```

#### Step 6: Execute PITR Restore

```bash
# Record restore start time
RESTORE_START=$(date +%s)

TARGET_TIME="$TARGET_TIME" \
BASE_BACKUP="$BASE_BACKUP" \
WAL_ARCHIVE="$WAL_ARCHIVE" \
CONFIRM_PITR_RESTORE=YES \
./ops/pitr_restore.sh
```

#### Step 7: Wait for Service Stabilization

```bash
# Wait up to 2 minutes for API to become ready
for i in {1..24}; do
  if curl -fsS http://staging:8000/healthz > /dev/null 2>&1; then
    echo "API ready after $((i * 5)) seconds"
    break
  fi
  sleep 5
done
```

#### Step 8: Post-Restore Health Checks

```bash
curl -fsS http://staging:8000/healthz | tee /tmp/healthz_post.json | jq .
curl -fsS http://staging:8000/readyz | tee /tmp/readyz_post.json | jq .
```

#### Step 9: Data Integrity Verification

```bash
# Verify row counts (should match pre-drill or be slightly lower due to recovery point)
docker compose exec -T db psql -U postgres -d cleaning -c \
  "SELECT 'bookings' as tbl, COUNT(*) FROM bookings
   UNION ALL SELECT 'leads', COUNT(*) FROM leads
   UNION ALL SELECT 'client_users', COUNT(*) FROM client_users;"

# Verify marker does NOT exist (proves PITR recovered to before insertion)
docker compose exec -T db psql -U postgres -d cleaning -c \
  "SELECT COUNT(*) FROM _pitr_drill_markers;" 2>/dev/null || echo "Table not found (expected)"
```

#### Step 10: Run Smoke Tests

```bash
API_BASE_URL=http://staging:8000 \
WEB_BASE_URL=http://staging:3000 \
./ops/smoke.sh
```

---

## Validation Steps

### Required Validations

All drills must verify the following:

#### Health Endpoint Checks

| Endpoint | Check | Pass Criteria |
|----------|-------|---------------|
| `/healthz` | HTTP status code | Returns `200` |
| `/healthz` | JSON `status` field | `"ok"` or `"ready"` |
| `/healthz` | JSON `db_connected` | `true` |
| `/readyz` | HTTP status code | Returns `200` |
| `/readyz` | JSON `status` field | `"ready"` |
| `/readyz` | JSON `migrations_current` | `true` |

#### Database Checks

| Check | Method | Pass Criteria |
|-------|--------|---------------|
| Database connectable | `pg_isready` | Exit code `0` |
| Core tables exist | Query `bookings`, `leads` | No error, returns count |
| Data is recent | `MAX(created_at)` check | Timestamp within expected range |
| Recovery completed | `pg_is_in_recovery()` | Returns `false` |

#### Service Checks

| Service | Check | Pass Criteria |
|---------|-------|---------------|
| PostgreSQL | Container running | `docker compose ps db` shows "Up" |
| API | Container running | `docker compose ps api` shows "Up" |
| Web | Container running | `docker compose ps web` shows "Up" |
| Jobs | Container running (if enabled) | `docker compose ps jobs` shows "Up" |

#### Smoke Tests

Run `ops/smoke.sh` and verify all checks pass:

- API `/healthz` accessible
- Web frontend accessible
- No 5xx errors in response

### Optional Validations

Additional checks for comprehensive drills:

- [ ] Create a test booking via API
- [ ] View an existing invoice
- [ ] Trigger a webhook retry
- [ ] Verify background job processing

---

## Success Criteria

### Pass/Fail Definition

A drill is **PASSED** if ALL of the following are true:

| Criterion | Requirement |
|-----------|-------------|
| **RTO met** | Total time from drill start to healthy `/readyz` < 90 minutes |
| **Health endpoints healthy** | Both `/healthz` and `/readyz` return 200 with expected status |
| **Database connected** | `db_connected=true` in health response |
| **Migrations current** | `migrations_current=true` in readiness response |
| **Smoke tests pass** | `ops/smoke.sh` exits with code 0 |
| **No critical errors** | No unrecoverable errors during restore process |

A drill is **FAILED** if ANY of the following occur:

- RTO exceeded (> 90 minutes to healthy state)
- Health endpoints return non-200 status
- Database connection fails after restore
- Smoke tests fail
- Restore script exits with non-zero code
- Data corruption detected (unexpected record counts, constraint violations)

### Conditional Pass

A drill may be marked **PASSED WITH OBSERVATIONS** if:

- RTO target met but with warnings
- Minor issues resolved during drill
- Documentation gaps identified but drill completed

All observations must be documented for follow-up.

### RTO Calculation

```
RTO = (Restore completion time) + (Service stabilization time)
    = (Time when pitr_restore.sh completes) + (Time until /readyz returns 200)
```

Record both components in the drill report.

---

## Reporting Format

### Drill Report Template

Use this template for all drill reports. Reports are saved to `ops/drill-reports/`.

```markdown
# PITR Restore Drill Report

## Summary

| Field | Value |
|-------|-------|
| **Drill ID** | `pitr_drill_YYYYMMDDTHHMMSSZ` |
| **Date (UTC)** | YYYY-MM-DD |
| **Status** | PASSED / FAILED / PASSED WITH OBSERVATIONS |
| **Environment** | staging |
| **Primary Operator** | [Name] |
| **Secondary Reviewer** | [Name] |

## Timing

| Metric | Value | Target |
|--------|-------|--------|
| Drill start (UTC) | HH:MM:SS | - |
| Drill end (UTC) | HH:MM:SS | - |
| Total duration | XX minutes | < 90 min |
| Restore duration | XX minutes | - |
| Service stabilization | XX seconds | < 120 sec |
| **RTO achieved** | XX minutes | < 90 min |

## Backup Artifacts Used

| Artifact | Filename | Size | Age |
|----------|----------|------|-----|
| Base backup | `basebackup_YYYYMMDDTHHMMSSZ.tar.gz` | XX MB | XX hours |
| WAL archive | `wal_archive_YYYYMMDDTHHMMSSZ.tar.gz` | XX MB | XX hours |
| Recovery target | `YYYY-MM-DD HH:MM:SS UTC` | - | - |

## Validation Results

### Health Checks

| Check | Pre-Drill | Post-Drill | Pass |
|-------|-----------|------------|------|
| `/healthz` status | ready | ready | YES |
| `/healthz` db_connected | true | true | YES |
| `/readyz` status | ready | ready | YES |
| `/readyz` migrations_current | true | true | YES |

### Data Integrity

| Table | Pre-Drill Count | Post-Drill Count | Variance | Pass |
|-------|-----------------|------------------|----------|------|
| bookings | XXXX | XXXX | 0 | YES |
| leads | XXXX | XXXX | 0 | YES |
| client_users | XXXX | XXXX | 0 | YES |

### Service Status

| Service | Status | Pass |
|---------|--------|------|
| db | Up | YES |
| api | Up | YES |
| web | Up | YES |
| jobs | Up | YES |

### Smoke Tests

| Test | Result |
|------|--------|
| API health check | PASS |
| Web frontend check | PASS |
| Overall | PASS |

## Issues Encountered

<!-- List any issues, even if resolved -->

- None

## Observations

<!-- Notes for future improvement -->

- None

## Follow-Up Actions

<!-- Required actions from this drill -->

| Action | Owner | Due Date | Status |
|--------|-------|----------|--------|
| None required | - | - | - |

---

*Report generated: YYYY-MM-DDTHH:MM:SSZ*
*Next scheduled drill: YYYY-MM-DD (Q# YYYY)*
```

### Report Storage

1. **Automated reports:** Saved to `ops/drill-reports/pitr_drill_YYYYMMDDTHHMMSSZ.md`
2. **Manual reports:** Create using template, save to same directory
3. **Retention:** Keep all drill reports for at least 2 years
4. **Archive:** Optionally upload to shared documentation (Confluence, Notion, etc.)

### Report Distribution

After each drill:

1. Share report in team channel (Slack, Teams, etc.)
2. File report in `ops/drill-reports/`
3. Update drill tracking spreadsheet (if maintained)
4. Add any follow-up actions to team task tracker

---

## Post-Drill Activities

### Immediate (Within 1 Hour)

- [ ] **Report completed:** Fill out all sections of drill report
- [ ] **Report shared:** Post summary to team channel
- [ ] **Issues logged:** Create tickets for any identified issues
- [ ] **Staging verified:** Confirm staging is operational for other uses

### Within 1 Week

- [ ] **Follow-ups addressed:** Complete any identified action items
- [ ] **Documentation updated:** Update procedures if gaps were found
- [ ] **Scripts improved:** Apply any fixes to drill/restore scripts
- [ ] **Next drill scheduled:** Confirm next quarterly drill on calendar

### Quarterly Review

After each quarter's drill:

1. **Trend analysis:** Compare RTO across quarters
2. **Process improvement:** Identify patterns in issues/observations
3. **Training needs:** Note any skill gaps observed
4. **Tool updates:** Evaluate if tooling improvements are needed

### Drill Tracking

Maintain a simple tracking table for historical reference:

| Quarter | Date | RTO Achieved | Status | Report Link | Notes |
|---------|------|--------------|--------|-------------|-------|
| Q1 2026 | 2026-01-17 | 45 min | PASSED | [Link] | - |
| Q2 2026 | 2026-04-16 | - | SCHEDULED | - | - |

---

## Escalation Procedures

### During Drill

If issues occur during the drill:

| Scenario | Action |
|----------|--------|
| Restore script fails | Check PostgreSQL logs (`docker compose logs db`), retry once, then escalate |
| Services won't start | Check container logs, verify disk space, escalate if unresolved in 15 min |
| Data appears corrupted | Stop drill, preserve current state, escalate immediately |
| RTO at risk (> 60 min) | Notify escalation contact, continue troubleshooting |

### Escalation Contacts

| Level | Criteria | Contact |
|-------|----------|---------|
| **L1** | Technical issues during drill | On-call engineer |
| **L2** | RTO exceeded or drill failed | Engineering lead |
| **L3** | Data integrity concerns | DB/Data owner |

### Post-Drill Escalation

If drill **FAILED**:

1. **Immediate:** Notify engineering lead within 1 hour
2. **Root cause:** Document failure reason in report
3. **Remediation:** Create action items with owners and due dates
4. **Re-drill:** Schedule follow-up drill within 2 weeks after fixes applied
5. **Postmortem:** If failure indicates production risk, schedule review meeting

### Production Impact Assessment

After a failed drill, assess production risk:

| Question | Yes Action | No Action |
|----------|------------|-----------|
| Is production using the same backup scripts? | Verify production backups manually | Document difference |
| Are production WAL archives healthy? | Confirm heartbeat file age | Investigate sync issues |
| Is there a workaround for the failure mode? | Document workaround | Escalate as P1 |

---

## Appendix

### Quick Reference Commands

```bash
# Check backup health
cat /opt/backups/postgres/LAST_BASEBACKUP.txt
cat ops/state/wal_sync_last_ok.txt

# List available backups
ls -lah /opt/backups/postgres/basebackup_*.tar.gz
ls -lah /opt/backups/postgres/wal_archive_*.tar.gz

# Run automated drill
TARGET_ENV=staging CONFIRM_DRILL=YES ./ops/pitr_restore_drill.sh

# Run manual PITR restore
TARGET_TIME="2026-01-25 14:30:00 UTC" \
BASE_BACKUP=/opt/backups/postgres/basebackup_20260125T120000Z.tar.gz \
WAL_ARCHIVE=/opt/backups/postgres/wal_archive_20260125T120000Z.tar.gz \
CONFIRM_PITR_RESTORE=YES \
./ops/pitr_restore.sh

# Verify restore
./ops/pitr_verify.sh

# Run smoke tests
API_BASE_URL=http://staging:8000 WEB_BASE_URL=http://staging:3000 ./ops/smoke.sh
```

### Related Documentation

- [DISASTER_RECOVERY.md](./DISASTER_RECOVERY.md) - Full DR procedures
- [OPERATIONS.md](../OPERATIONS.md) - Backup & restore operations
- `ops/pitr_restore_drill.sh` - Automated drill script
- `ops/pitr_restore.sh` - PITR restore script
- `ops/pitr_verify.sh` - Post-restore verification script

### Revision History

| Date | Version | Author | Changes |
|------|---------|--------|---------|
| 2026-01-25 | 1.0 | - | Initial version |
