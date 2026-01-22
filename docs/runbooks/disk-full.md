# Runbook: Disk Full

**Alert signal:** Disk usage > 85% or write failures in logs.

## Quick diagnosis

```bash
# Identify full volumes
df -h

# Find large directories (top-level)
du -h -d 1 /opt/cleaning | sort -hr | head -n 15
```

## Likely causes

- Unbounded logs in `logs/` or Docker logs.
- Large uploads in `/opt/cleaning/var/uploads`.
- Backup directory growth in `/opt/backups/postgres`.
- Old Docker images/volumes not pruned.

## Safe remediation steps

1. **Clear old backups after verifying restore:**
   ```bash
   ls -lh /opt/backups/postgres
   # Remove older backups only after confirming the newest one is good
   rm -f /opt/backups/postgres/cleaning_OLD.sql.gz
   ```
2. **Rotate/remove old logs:**
   ```bash
   ls -lh /opt/cleaning/logs
   rm -f /opt/cleaning/logs/*.log
   ```
3. **Prune unused Docker artifacts:**
   ```bash
   docker system prune -f
   ```
4. **Re-check disk usage:**
   ```bash
   df -h
   ```

## Rollback / restore pointers

- Ensure at least one verified database backup remains before removing older archives.
- Use `OPERATIONS.md` backup restore steps if a restore is required.

## Escalation roles

- **Primary:** On-call engineer (Ops)
- **Secondary:** Infrastructure owner
- **Tertiary:** Security/Compliance (if log retention is regulated)
