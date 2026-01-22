# Runbook: High Resource Usage (CPU/Memory)

**Alert signal:** CPU > 80% sustained, memory > 85%, or OOM kills in container logs.

## Quick diagnosis

```bash
# Check container resource usage
docker stats --no-stream

# Detailed memory/CPU per service
cd /opt/cleaning

docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}"

# Check for OOM kills
docker compose logs --tail=500 | grep -i "oom\|killed\|memory"

# Identify slow queries
docker compose exec db psql -U postgres cleaning -c \
  "SELECT pid, now() - query_start AS duration, query FROM pg_stat_activity WHERE state = 'active' ORDER BY duration DESC LIMIT 10;"
```

## Likely causes

- Inefficient queries causing DB CPU spikes.
- Connection pool exhaustion or leak.
- Memory leak in API container (unbounded cache, large request payloads).
- Background jobs consuming excessive resources.
- Docker container limits too low for workload.

## Safe remediation steps

1. **Identify the resource-intensive container:**
   ```bash
   docker stats --no-stream
   ```
2. **For database CPU spikes:**
   - Check slow queries:
     ```bash
     docker compose exec db psql -U postgres cleaning -c \
       "SELECT * FROM pg_stat_activity WHERE state = 'active';"
     ```
   - Terminate long-running queries if safe:
     ```bash
     docker compose exec db psql -U postgres cleaning -c \
       "SELECT pg_terminate_backend(<pid>);"
     ```
3. **For API memory issues:**
   - Restart API container:
     ```bash
     docker compose restart api
     ```
   - Check connection pool settings in `backend/app/settings.py`.
4. **Increase container resource limits** (if workload justifies):
   - Edit `docker-compose.yml` to increase memory/CPU limits:
     ```yaml
     api:
       deploy:
         resources:
           limits:
             memory: 2G
             cpus: '1.5'
     ```
   - Redeploy:
     ```bash
     docker compose up -d
     ```

## Rollback / restore pointers

- If a recent deploy caused the spike, rollback to previous version:
  ```bash
  cd /opt/cleaning
  git reset --hard <good_sha>
  ./ops/deploy.sh
  ```
- If queries are the issue, review and optimize or add indexes via migration.

## Escalation roles

- **Primary:** On-call engineer (Ops)
- **Secondary:** Backend lead (for query optimization)
- **Tertiary:** Infrastructure owner (for capacity planning)
