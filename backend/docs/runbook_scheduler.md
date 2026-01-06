# Scheduler Runbook

Use this runbook to configure recurring maintenance calls (cron or Cloudflare Scheduler) and to monitor job heartbeats. All admin endpoints are Basic Auth protected; do **not** expose them publicly without IP allowlists and strong credentials.

## Prerequisites
- Environment variables exported for convenience:
  - `API_BASE=https://api.example.com`
  - `ADMIN_BASIC_USERNAME` / `ADMIN_BASIC_PASSWORD`
- Network path to the API restricted to trusted cron/Scheduler runners.
- `JOBS_ENABLED=true` in production so `/readyz` enforces a fresh heartbeat when the runner should be online. Keep `JOB_HEARTBEAT_REQUIRED=true` for explicit gating in non-prod.
- `JOB_HEARTBEAT_TTL_SECONDS` defaults to 180 seconds (3 minutes). Tune lower only if the runner loop interval is also lower.
- Set `JOB_RUNNER_ID` (hostname/pod name) to make heartbeats traceable in logs/metrics.

## Enabling the jobs runner in production
- In `.env.production`, set `JOBS_ENABLED=true`, `JOB_HEARTBEAT_REQUIRED=true`, and keep `JOB_HEARTBEAT_TTL_SECONDS` at 180s unless you intentionally shorten the loop cadence.
- Start the runner as its own container or process: `python -m app.jobs.run --interval 60` (Compose service `jobs` is already wired). The API container can run alongside it or independently; both just need DB access.
- `/readyz` will return 503 within ~3 minutes if the runner dies or stops writing heartbeats. Metrics (`job_runner_up`, `job_heartbeat_age_seconds`) flip as well.
- Optional: set `JOB_RUNNER_ID=$(hostname)` (or the deployment name) so `/v1/admin/jobs/status` and logs report which worker wrote the heartbeat.

## Required scheduled actions
Use POST requests to the admin endpoints below. Frequencies are safe defaults; adjust only if downstream capacity and queues are healthy.

| Action | Endpoint | Recommended frequency | Rationale | Example |
| --- | --- | --- | --- | --- |
| Cleanup orphaned data and reconcile straggler jobs | `/v1/admin/cleanup` | Daily at 04:00 UTC | Runs heavier maintenance; off-peak timing avoids contention with daytime traffic. | `curl -u "$ADMIN_BASIC_USERNAME:$ADMIN_BASIC_PASSWORD" -X POST "$API_BASE/v1/admin/cleanup"` |
| Email inbound scan | `/v1/admin/email-scan` | Every 5 minutes | Keeps inbox ingestion responsive; prevents large batches from piling up. | `curl -u "$ADMIN_BASIC_USERNAME:$ADMIN_BASIC_PASSWORD" -X POST "$API_BASE/v1/admin/email-scan"` |
| Data retention cleanup | `/v1/admin/retention/cleanup` | Daily at 02:00 UTC | Applies retention policies without clashing with the heavier cleanup task. | `curl -u "$ADMIN_BASIC_USERNAME:$ADMIN_BASIC_PASSWORD" -X POST "$API_BASE/v1/admin/retention/cleanup"` |
| Export DLQ replay | `/v1/admin/export-dead-letter` | Every 15 minutes | Replays failed exports promptly while giving time for upstream fixes. | `curl -u "$ADMIN_BASIC_USERNAME:$ADMIN_BASIC_PASSWORD" -X POST "$API_BASE/v1/admin/export-dead-letter"` |
| Outbox DLQ replay | `/v1/admin/outbox/dead-letter` | Every 15 minutes | Keeps notification/webhook dead letters drained; align with export replay cadence. | `curl -u "$ADMIN_BASIC_USERNAME:$ADMIN_BASIC_PASSWORD" -X POST "$API_BASE/v1/admin/outbox/dead-letter"` |

## Optional jobs via the runner module
Use the built-in runner for jobs that need process-local execution or to backfill during incidents.

```bash
# Storage janitor: removes orphaned files; run daily during a quiet window
python -m app.jobs.run --job storage_janitor --once

# Outbox delivery loop: for environments without an external scheduler
python -m app.jobs.run --job outbox-delivery --once
```

Add `--interval <n>` if you want the runner to loop instead of a single execution. Keep the same frequencies as above when wiring a long-running process.

## Monitoring and heartbeats
- Status endpoint: `curl -u "$ADMIN_BASIC_USERNAME:$ADMIN_BASIC_PASSWORD" "$API_BASE/v1/admin/jobs/status"`
- Fields per job:
  - `name`: job identifier (e.g., `email-dlq`, `jobs-runner`).
  - `last_heartbeat`: last heartbeat timestamp recorded by the runner.
  - `runner_id`: pod/host identifier (set via `JOB_RUNNER_ID` or hostname fallback).
  - `last_success_at`: last successful completion time.
  - `consecutive_failures`: non-zero when recent attempts failed; should return to 0 after a success.
  - `last_error` / `last_error_at`: populated when failures occur; clear once the job succeeds again.
- Interpretation:
  - Heartbeat older than `JOB_HEARTBEAT_TTL_SECONDS` → restart the scheduler/runner pod or VM. The `job_heartbeat_age_seconds{job="jobs-runner"}` gauge and `/readyz` both surface the age.
  - Rising `consecutive_failures` with `last_error` set → investigate the specific job (e.g., provider outage); pause retries if causing load.
  - `/readyz` will return 503 when heartbeats are stale and either `JOBS_ENABLED` or `JOB_HEARTBEAT_REQUIRED` is true, helping alerting catch broken schedulers.

## Manual heartbeat verification
- API: `curl -s "$API_BASE/readyz" | jq '.checks[] | select(.name=="jobs")'` shows age, runner ID, and threshold (503 if stale).
- Admin endpoint: `curl -u "$ADMIN_BASIC_USERNAME:$ADMIN_BASIC_PASSWORD" "$API_BASE/v1/admin/jobs/status"` lists heartbeats per job with runner IDs.
- Database (psql): `SELECT name, runner_id, last_heartbeat FROM job_heartbeats ORDER BY last_heartbeat DESC LIMIT 5;`

## Optional Better Stack heartbeat integration
- Create a Better Stack Heartbeat monitor and copy its unique URL (e.g., `https://uptime.betterstack.com/heartbeat/<token>`).
- Wrap the runner invocation in your scheduler to ping Better Stack after a successful loop:
  - Cron example: `* * * * * . /etc/profile && python -m app.jobs.run --interval 60 --once && curl -fsS https://uptime.betterstack.com/heartbeat/<token> >/dev/null`
- For long-running containers, sidecar a lightweight cron or Kubernetes `CronJob` that hits the Better Stack URL every minute. Keep the cadence aligned with `JOB_HEARTBEAT_TTL_SECONDS` so alerts fire before `/readyz` degrades.
