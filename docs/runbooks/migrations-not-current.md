# Runbook: Migrations Not Current

**Alert signal:** `/healthz` shows `migrations_current: false` or `current_revision` != `expected_revision`.

## Quick diagnosis

```bash
curl -fsS https://api.panidobro.com/healthz | jq

cd /opt/cleaning

docker compose exec api alembic current

docker compose exec api alembic heads
```

## Likely causes

- Deploy completed but migrations were not run.
- Multiple Alembic heads after a merge.
- Migration failed midway (locked table or permissions).

## Safe remediation steps

1. **Run migrations to head:**
   ```bash
   docker compose exec api alembic upgrade head
   ```
2. **If multiple heads exist:**
   - Stop deployment, merge heads in a new migration.
   - See `OPERATIONS.md` for merge steps.
3. **Verify health:**
   ```bash
   curl -fsS https://api.panidobro.com/healthz
   ```

## Rollback / restore pointers

- Do **not** downgrade migrations in production.
- If a deploy introduced the mismatch, rollback the application code only:
  ```bash
  cd /opt/cleaning
  git reset --hard <good_sha>
  ./ops/deploy.sh
  ```

## Escalation roles

- **Primary:** On-call engineer (Ops)
- **Secondary:** Backend lead
- **Tertiary:** Data/DB owner
