# Runbook: Backup Stale

**Alert signal:** Backup heartbeat older than 26 hours or missing backup files.

## Quick diagnosis

```bash
cd /opt/cleaning

# Check heartbeat timestamp
cat /opt/cleaning/ops/state/backup_last_ok.txt

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
   docker compose exec db pg_dump -U postgres cleaning > /opt/backups/postgres/cleaning_manual.sql
   gzip /opt/backups/postgres/cleaning_manual.sql
   ```
2. **Restart cron or the backup job:**
   - Validate `crontab -l` for `/opt/cleaning/ops/backup.sh`.
3. **Re-run verification:**
   ```bash
   /opt/cleaning/ops/backup_verify.sh
   ```

## Rollback / restore pointers

- If backups are corrupted, restore from the last known good archive.
- See `OPERATIONS.md` -> Backup & Restore for restore procedure.

## Escalation roles

- **Primary:** On-call engineer (Ops)
- **Secondary:** Data/DB owner
- **Tertiary:** Security/Compliance (if retention is required)
