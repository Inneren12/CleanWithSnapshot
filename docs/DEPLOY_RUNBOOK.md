# Deploy Runbook

Use this runbook for manual deploys when automation is unavailable. Commands assume the repo is checked out to `/opt/cleaning` w
ith a populated `.env`.

## Pre-requisites
- Docker Engine and Docker Compose plugin installed
- `.env` present with target environment secrets (dev/stage/prod)
- Database reachable from the host

## Deploy Steps
1. Fetch the desired revision:
   ```bash
   git fetch origin
   git checkout <branch-or-sha>
   git reset --hard <branch-or-sha>
   ```
2. Build images:
   ```bash
   docker compose build
   ```
3. Apply migrations (runs inside API container after services are up):
   ```bash
   docker compose up -d --remove-orphans
   docker compose exec api alembic upgrade head
   ```
4. Restart services to pick up new code and assets:
   ```bash
   docker compose restart api web caddy
   ```

## Post-Deploy Checks
- API readiness: `curl -fsS "$API_BASE_URL/readyz"`
- Web smoke: `./scripts/smoke.sh`
- Database health: `docker compose exec db pg_isready`
- Logs clean: `docker compose logs --tail=200 api web caddy`

## Environment Separation (optional)
- **dev**: permissive CORS, test credentials, lightweight monitoring
- **stage**: production-like configuration, real integrations in test mode, gated access
- **prod**: strict secrets, `APP_ENV=prod`, monitoring and alerting enabled, backups verified
