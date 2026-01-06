# Release Checklist

Use this checklist to gate releases before promoting a commit to staging or production. Treat every unchecked box as a hard stop. Commands assume the repository root unless noted.

## Go/No-Go Readiness
- [ ] CI pipeline green for the target commit (all required checks: **API - Build & Test**, **Web - Build**, **API - Prod Config Validation**, **Infrastructure - Validation**).
- [ ] Release candidate tagged or commit SHA recorded and shared with stakeholders.
- [ ] Database migrations reviewed for safety (idempotent, non-blocking where possible) and owners sign off.
- [ ] Feature flags/toggles documented with desired defaults per environment.

## Pre-Deploy Validation
- [ ] Backend unit tests (when API logic changed):
  ```bash
  cd backend
  pytest -v -m "not smoke and not postgres" --ignore=tests/smoke --tb=short
  ```
- [ ] Frontend build (when UI/assets changed):
  ```bash
  cd web
  npm ci
  npx tsc --noEmit
  npm run lint --if-present
  npm run build
  ```
- [ ] Secrets & configs verified for target environment (no placeholders, expected hostnames/ports configured).
- [ ] Observability checks updated (dashboards/alerts tuned if new metrics or error types are introduced).

## Deployment Steps (manual fallback)
- [ ] Pull target revision and build images:
  ```bash
  git fetch origin
  git checkout <branch-or-sha>
  git reset --hard <branch-or-sha>
  docker compose build
  ```
- [ ] Apply database migrations safely (works on clean deploys):
  ```bash
  docker compose up -d db api
  docker compose exec -T api alembic upgrade head
  ```
- [ ] Verify Alembic state when needed (no assumptions about revision format):
  ```bash
  CURRENT=$(docker compose exec -T api alembic current | awk '{print $1}' | head -1)
  HEAD=$(docker compose exec -T api alembic heads | awk '{print $1}' | head -1)
  echo "Current: $CURRENT"; echo "Head: $HEAD"
  ```
- [ ] Restart application services:
  ```bash
  docker compose restart api web caddy
  ```

## Smoke Tests
- [ ] API readiness endpoint returns HTTP 200 and reports readiness:
  ```bash
  curl -fsS "$API_BASE_URL/readyz"
  curl -fsS "$API_BASE_URL/readyz" | jq -e '(.status == "ok") or (.ok == true)'
  ```
- [ ] Web root returns 200: `curl -fsS "$WEB_BASE_URL/"`.
- [ ] Repository smoke script passes: `./scripts/smoke.sh`.
- [ ] Logs clean for api/web/caddy after deploy (`docker compose logs --tail=200 api web caddy`).

## Sign-off
- [ ] Deployment owner confirms rollback plan and monitoring coverage.
- [ ] Approver acknowledges Go/No-Go decision and authorizes release.
- [ ] Post-release communication drafted (changelog, customer notes, on-call handoff).
