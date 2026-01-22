# Runbook: Redis Down

**Alert signal:** Redis health checks failing or API log shows cache/session errors.

## Quick diagnosis

```bash
cd /opt/cleaning

docker compose ps redis

docker compose logs --tail=200 redis

docker compose exec redis redis-cli ping
```

## Likely causes

- Redis container crashed or restart loop.
- Disk full on Redis volume.
- Memory pressure or eviction storms.
- Incorrect `REDIS_URL` in `.env`.

## Safe remediation steps

1. **Restart Redis container:**
   ```bash
   docker compose restart redis
   docker compose exec redis redis-cli ping
   ```
2. **Check memory and disk usage:**
   ```bash
   docker stats --no-stream redis
   df -h
   ```
3. **Verify connection string:**
   ```bash
   grep REDIS_URL /opt/cleaning/.env
   ```

## Rollback / restore pointers

- Redis is a cache; safe to clear if needed:
  ```bash
  docker compose exec redis redis-cli FLUSHALL
  ```
- If the issue started after deploy, rollback the deployment:
  ```bash
  cd /opt/cleaning
  git reset --hard <good_sha>
  ./ops/deploy.sh
  ```

## Escalation roles

- **Primary:** On-call engineer (Ops)
- **Secondary:** Backend lead
- **Tertiary:** Infrastructure owner
