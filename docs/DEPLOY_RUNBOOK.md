# Deploy Runbook

This runbook documents the manual deploy flow for the Cleaning service when CI/CD automation is unavailable. All commands assume the repository is checked out to `/opt/cleaning` on the target host and that Docker Compose is available.

## Pre-requisites
- Docker Engine with the Compose plugin installed and running.
- `.env` file present in the repo root with the target environment's secrets (dev/stage/prod).
- Network access to the database host and any upstream dependencies.
- Sufficient disk space for image builds and database migrations.

## Prepare the Code
1. Fetch the desired revision and reset the working tree:
   ```bash
   git fetch origin
   git checkout <branch-or-sha>
   git reset --hard <branch-or-sha>
   ```
2. Review release notes and confirm any manual toggles or feature flags required for the environment.

## Build Images
Build fresh images to avoid stale layers:
```bash
docker compose build
```

## Apply Database Migrations
Use a migration path that works for both existing and clean deployments. Do **not** exec into `api` before it is started. Prefer a single consistent pattern:
```bash
docker compose up -d db api
# Once containers are healthy, run migrations inside the running API container
docker compose exec -T api alembic upgrade head
```

### Verifying Alembic State (optional but recommended)
If you need to confirm the current revision before and after the upgrade without assuming revision format lengths:
```bash
CURRENT=$(docker compose exec -T api alembic current | awk '{print $1}' | head -1)
HEAD=$(docker compose exec -T api alembic heads | awk '{print $1}' | head -1)
echo "Current: $CURRENT"
echo "Head:    $HEAD"
if [ "$CURRENT" = "$HEAD" ]; then
  echo "✓ Alembic is at head"
else
  echo "⚠ Alembic is behind: run upgrade"
fi
```

## Restart Services
After migrations finish, restart the app-facing services to pick up the new code and assets:
```bash
docker compose restart api web caddy
```
If the API container was recreated during migrations, a restart may be a no-op but keeps the sequence explicit.

## Post-Deploy Checks
- **API readiness**: Expect HTTP 200 and a readiness indicator. Examples:
  ```bash
  curl -fsS "$API_BASE_URL/readyz"
  curl -fsS "$API_BASE_URL/readyz" | jq -e '(.status == "ok") or (.ok == true)'
  ```
- **Web smoke**: Run the repository smoke script from root: `./scripts/smoke.sh`.
- **Database health**: `docker compose exec db pg_isready`.
- **Logs clean**: `docker compose logs --tail=200 api web caddy` and check for errors.

## Environment Separation
- **dev**: Permissive CORS and test credentials; monitoring may be lighter.
- **stage**: Mirrors production configuration with gated access; real integrations may run in test mode.
- **prod**: Strict secrets and monitoring enabled; backups and alerting must be verified before changes.

## Rollback Guidance
1. Identify the previous known-good tag or commit.
2. Redeploy that revision using the same steps above (build, migrate if necessary, restart).
3. If rollback requires a down migration, confirm with database owners before running `alembic downgrade`.
4. Announce rollback completion in the team channel with the deployed revision and any outstanding risks.
