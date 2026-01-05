# Operations Runbook

## Source of truth
- The Git repository is the only source of truth. Do **not** edit code or configs directly on the VPS except for runtime secrets in `.env`.
- Keep runtime artifacts (`.env`, `logs/`, `pg_data/`, `caddy_data/`, `caddy_config/`, `var/`, `tmp/`) intact between deploys.

## Initial server setup
- Install Docker Engine and the Docker Compose plugin.
- Clone the repo to `/opt/cleaning` and ensure `origin` points to the authoritative remote.
- Place the production `.env` in `/opt/cleaning/.env` (never commit this file).
- Ensure backup and log directories exist and are writable by Docker (`logs/`, `/opt/backups/postgres`).

## Deploy (one button)
Run from `/opt/cleaning`:

```bash
./ops/deploy.sh
```

What it does:
1. Prints the current and updated git SHAs.
2. Fetches `origin/main` and hard resets the working tree while preserving `.env`, logs, and volumes.
3. Builds images (`docker compose build`) and starts the stack (`docker compose up -d --remove-orphans`).
4. Waits for Postgres readiness and runs `alembic upgrade head` inside the `api` container.
5. Runs smoke checks via `ops/smoke.sh` (API `/healthz`, web root) and fails if either endpoint is unhealthy.

If migrations alter long-lived connections, restart the affected services with `docker compose restart <service>` after the deploy; current migrations run inside the running `api` container and do not require an extra restart.

## Smoke checks
- API: `https://api.panidobro.com/healthz`
- Web: `https://panidobro.com/`
- Override with `API_BASE_URL` or `WEB_BASE_URL` when running `ops/smoke.sh` directly.

## Logs and health
- Check: `curl -fsS https://api.panidobro.com/healthz`
- Inspect: `docker compose ps`
- Logs: `docker compose logs --tail=200 api|caddy|db`

## Rollback
- Migrations are forward-only by default. Downgrades are not recommended unless explicitly supported and tested.
- To roll back code:
  1. Identify the previous known-good tag or SHA (e.g., from `git reflog`).
  2. Hard reset to that revision: `git fetch origin && git reset --hard <sha>`.
  3. Re-run `./ops/deploy.sh` to rebuild, restart, run migrations (no automatic downgrades), and smoke-test.
- If a migration is incompatible and no downgrade exists, prefer a forward fix and redeploy.

## Quick actions
- Restart: `docker compose restart api|caddy|db`
- Disk/RAM: `df -h`, `free -m`
