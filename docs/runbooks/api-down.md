# Runbook: API Down

**Alert signal:** API health checks failing or elevated 5xx error rate.

## Quick diagnosis

```bash
# Check container status
cd /opt/cleaning

# Service health
curl -fsS https://api.panidobro.com/healthz

docker compose ps api

docker compose logs --tail=200 api
```

```bash
# Check dependencies
curl -fsS https://api.panidobro.com/readyz

docker compose logs --tail=200 db

docker compose logs --tail=200 redis
```

## Likely causes

- API container crash or unhealthy deployment.
- Database unavailable or connection pool exhausted.
- Redis unavailable (cache/session failures).
- Missing or rotated environment variables.
- Recent migration not applied.

## Safe remediation steps

1. **Confirm recent deploy:**
   ```bash
   git -C /opt/cleaning log --oneline -5
   ```
2. **Restart API container:**
   ```bash
   docker compose restart api
   ```
3. **Verify migrations are current:**
   ```bash
   docker compose exec api alembic upgrade head
   ```
4. **Check dependency status:**
   ```bash
   docker compose ps db redis
   docker compose logs --tail=200 db
   docker compose logs --tail=200 redis
   ```
5. **If env vars missing:** compare `/opt/cleaning/.env` with expected variables in `docs/ENV_AUDIT_REPORT.md`.

## Rollback / restore pointers

- If the issue started after deploy, rollback to the last known good commit:
  ```bash
  cd /opt/cleaning
  git log --oneline -10
  git reset --hard <good_sha>
  ./ops/deploy.sh
  ```
- See `OPERATIONS.md` rollback section for full workflow.

## Escalation roles

- **Primary:** On-call engineer (Ops)
- **Secondary:** Backend lead
- **Tertiary:** Infrastructure owner
