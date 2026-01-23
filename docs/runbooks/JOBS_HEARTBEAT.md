# Runbook: Jobs Heartbeat Missing

**Alert signal:** `JobsHeartbeatMissing` firing because `job_runner_up` is `0` or `job_heartbeat_age_seconds` is greater than 5 minutes.

## Quick diagnosis

```bash
# Check job heartbeat health from readiness endpoint
curl -fsS https://api.panidobro.com/readyz | jq '.checks[] | select(.name=="jobs")'

# Check detailed job runner status
curl -fsS -u "$ADMIN_BASIC_USERNAME:$ADMIN_BASIC_PASSWORD" \
  https://api.panidobro.com/v1/admin/jobs/status | jq .

# Verify jobs container status
cd /opt/cleaning

docker compose ps jobs

# Review recent jobs logs
docker compose logs --tail=300 jobs
```

## Likely causes

- Jobs runner container stopped or stuck.
- `JOBS_ENABLED` or `JOB_HEARTBEAT_REQUIRED` misconfigured.
- Database connectivity problems preventing heartbeat writes.
- Clock drift or long pauses preventing heartbeat updates.

## Safe remediation steps

1. **Restart the jobs runner container:**
   ```bash
   docker compose restart jobs
   docker compose logs --tail=200 jobs
   ```
2. **Verify environment flags are enabled:**
   ```bash
   cat /opt/cleaning/.env | grep -E "JOBS_ENABLED|JOB_HEARTBEAT_REQUIRED|JOB_HEARTBEAT_TTL"
   ```
3. **Confirm database connectivity from the jobs container:**
   ```bash
   docker compose exec jobs python -c "from app.db import engine; engine.connect().close(); print('DB OK')"
   ```
4. **Run a single job loop to validate heartbeat updates:**
   ```bash
   docker compose exec jobs python -m app.jobs.run --once
   ```
5. **Re-check readiness:**
   ```bash
   curl -fsS https://api.panidobro.com/readyz | jq '.checks[] | select(.name=="jobs")'
   ```

## Rollback / restore pointers

- If a recent deploy broke the jobs runner, rollback:
  ```bash
  cd /opt/cleaning
  git log --oneline -10
  git reset --hard <good_sha>
  ./ops/deploy.sh
  ```

## Escalation roles

- **Primary:** On-call engineer (Ops)
- **Secondary:** Backend lead
- **Tertiary:** Infrastructure owner
