# Runbook: Job Scheduler Stale/Failing

**Alert signal:** `/readyz` shows stale job heartbeat or scheduled jobs not executing (DLQ backlog, stale exports, missed email sends).

## Quick diagnosis

```bash
# Check readiness endpoint for job status
curl -fsS https://api.panidobro.com/readyz | jq '.checks[] | select(.name=="jobs")'

# Check job heartbeat age
curl -fsS https://api.panidobro.com/readyz | jq '.checks[] | select(.name=="jobs") | .detail.age_seconds'

# Review job runner logs
cd /opt/cleaning

docker compose logs --tail=500 api | grep -i "job\|heartbeat\|scheduler"

# Check if jobs container is running
docker compose ps jobs
```

```bash
# Check DLQ backlog (sign of failing background jobs)
curl -fsS -u "$ADMIN_BASIC_USERNAME:$ADMIN_BASIC_PASSWORD" \
  "https://api.panidobro.com/v1/admin/queue/dlq?kind=all&limit=1"
```

## Likely causes

- Jobs container crashed or not started.
- `JOBS_ENABLED` not set or disabled.
- Database connectivity issues preventing heartbeat writes.
- Job runner process crashed inside container but container still running.
- Clock drift causing heartbeat staleness detection.

## Safe remediation steps

1. **Verify jobs container is running:**
   ```bash
   docker compose ps jobs
   docker compose logs --tail=200 jobs
   ```
2. **Restart jobs container:**
   ```bash
   docker compose restart jobs
   ```
3. **Verify environment configuration:**
   ```bash
   cat /opt/cleaning/.env | grep -E "JOBS_ENABLED|JOB_HEARTBEAT"
   ```
   - Ensure `JOBS_ENABLED=true` and `JOB_HEARTBEAT_REQUIRED=true` are set.
4. **Check database connectivity from jobs container:**
   ```bash
   docker compose exec jobs python -c "from app.db import engine; engine.connect().close(); print('DB OK')"
   ```
5. **Manually trigger job runner to verify:**
   ```bash
   docker compose exec jobs python -m app.jobs.run --once
   ```
6. **Check readiness again:**
   ```bash
   curl -fsS https://api.panidobro.com/readyz | jq
   ```

## Rollback / restore pointers

- If a recent deploy broke the job runner, rollback:
  ```bash
  cd /opt/cleaning
  git reset --hard <good_sha>
  ./ops/deploy.sh
  ```
- If DLQ has backlog, replay failed jobs after fixing root cause:
  ```bash
  curl -X POST -u "$ADMIN_BASIC_USERNAME:$ADMIN_BASIC_PASSWORD" \
    "https://api.panidobro.com/v1/admin/outbox/{id}/replay"
  ```

## Escalation roles

- **Primary:** On-call engineer (Ops)
- **Secondary:** Backend lead
- **Tertiary:** Infrastructure owner
