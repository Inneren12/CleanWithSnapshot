# Runbook: Backup Stale

**Alert signal:** Backup heartbeat older than 26 hours or missing backup files.

## Quick diagnosis

```bash
cd /opt/cleaning

# Check verification heartbeat timestamp
cat /opt/cleaning/ops/state/backup_last_ok.txt

# Check backup health marker used by /healthz/backup
cat /opt/backups/postgres/LAST_SUCCESS.txt

# List latest backups
ls -lh /opt/backups/postgres | tail -n 10
```

```bash
# Run verification script
/opt/cleaning/ops/backup_verify.sh
```

## Likely causes

- Cron job disabled or failed.
- Disk full or backup write failure.
- Postgres connection issues.
- Backup script permission changes.

## Safe remediation steps

1. **Run a manual backup:**
   ```bash
   /opt/cleaning/ops/backup_now.sh

   # Verify marker updated
   cat /opt/backups/postgres/LAST_SUCCESS.txt
   ```
2. **Restart cron or the backup job:**
   - Validate `crontab -l` for `/opt/cleaning/ops/backup_now.sh`.
   - There is **no** `backup.sh` in this repository; the cron job must invoke `backup_now.sh`.
   - If cron is missing, restoring it is part of incident resolution.
3. **Re-run verification:**
   ```bash
   /opt/cleaning/ops/backup_verify.sh
   ```

## Sanity check (/healthz/backup failing)

```bash
# Marker must exist and be recent
cat /opt/backups/postgres/LAST_SUCCESS.txt

# Manually run the backup job if needed
/opt/cleaning/ops/backup_now.sh

# Re-check health endpoint
curl -fsS http://localhost:8000/healthz/backup | jq .
```

## Rollback / restore pointers

- If backups are corrupted, restore from the last known good archive.
- See `OPERATIONS.md` -> Backup & Restore for restore procedure.

## Escalation roles

- **Primary:** On-call engineer (Ops)
- **Secondary:** Data/DB owner
- **Tertiary:** Security/Compliance (if retention is required)
