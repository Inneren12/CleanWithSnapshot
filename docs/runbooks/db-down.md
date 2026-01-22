# Runbook: Database Down

**Alert signal:** API health shows `db_connected: false`, or Postgres health checks failing.

## Quick diagnosis

```bash
cd /opt/cleaning

docker compose ps db

docker compose logs --tail=200 db

docker compose exec db pg_isready
```

```bash
# Check disk space for database volume
df -h /opt/backups /opt/cleaning
```

## Likely causes

- Postgres container crashed or stuck in recovery.
- Disk full or volume permissions issue.
- Corrupted WAL or failed startup after power loss.
- Invalid credentials in `.env`.

## Safe remediation steps

1. **Restart Postgres container:**
   ```bash
   docker compose restart db
   docker compose exec db pg_isready
   ```
2. **Check disk availability:**
   ```bash
   df -h
   ```
3. **Verify credentials:**
   ```bash
   grep POSTGRES /opt/cleaning/.env
   ```
4. **Review Postgres logs for recovery errors:**
   ```bash
   docker compose logs --tail=200 db
   ```

## Rollback / restore pointers

- If data is corrupted or unrecoverable, restore from the latest backup:
  - See `OPERATIONS.md` -> Backup & Restore section for exact commands.
- If a deploy caused startup issues, rollback the deployment:
  ```bash
  cd /opt/cleaning
  git reset --hard <good_sha>
  ./ops/deploy.sh
  ```

## Escalation roles

- **Primary:** On-call engineer (Ops)
- **Secondary:** Data/DB owner
- **Tertiary:** Infrastructure owner
