# Runbook: Outbox Backlog High

**Alert signal:** `OutboxBacklogHigh` or `OutboxDeliveryErrorsHigh` firing because `outbox_lag_seconds` is high or delivery errors are elevated.

## Quick diagnosis

```bash
# Check outbox queue depth and lag metrics in Prometheus
# (Use Grafana dashboard "Outbox Overview" for a quick view.)

# Check DLQ/backlog summary (admin credentials required)
curl -fsS -u "$ADMIN_BASIC_USERNAME:$ADMIN_BASIC_PASSWORD" \
  "https://api.panidobro.com/v1/admin/queue/dlq?kind=outbox&limit=1" | jq .

# Review recent outbox/job logs
cd /opt/cleaning

docker compose logs --tail=300 jobs | grep -i "outbox\|delivery\|error"
```

## Likely causes

- Outbox delivery job is not running or stalled.
- Downstream provider failures (email/SMS/webhook endpoints).
- Increased backlog due to a burst of events or retries.
- Database or network latency slowing delivery.

## Safe remediation steps

1. **Ensure jobs runner is healthy and running:**
   ```bash
   docker compose ps jobs
   docker compose logs --tail=200 jobs
   ```
2. **Run an on-demand outbox delivery loop:**
   ```bash
   docker compose exec jobs python -m app.jobs.run --job outbox-delivery --once
   ```
3. **Check for persistent delivery errors:**
   ```bash
   docker compose logs --tail=200 jobs | grep -i "outbox\|delivery\|error"
   ```
4. **If DLQ is growing, replay after fixing root cause:**
   ```bash
   curl -X POST -u "$ADMIN_BASIC_USERNAME:$ADMIN_BASIC_PASSWORD" \
     "https://api.panidobro.com/v1/admin/outbox/dead-letter"
   ```
5. **Verify backlog and lag trend down in Grafana.**

## Rollback / restore pointers

- If a deploy increased delivery failures, rollback:
  ```bash
  cd /opt/cleaning
  git log --oneline -10
  git reset --hard <good_sha>
  ./ops/deploy.sh
  ```
- Refer to [DLQ_RUNBOOK.md](../DLQ_RUNBOOK.md) for detailed replay steps.

## Escalation roles

- **Primary:** On-call engineer (Ops)
- **Secondary:** Backend lead
- **Tertiary:** Infrastructure owner
