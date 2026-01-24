# Playwright E2E in CI

This repo runs Playwright end-to-end checks in GitHub Actions using Docker Compose.
The workflow is defined in `.github/workflows/e2e.yml` and is designed to keep Playwright
binaries ephemeral (no package manifest changes).

## What the workflow does

1. Creates a minimal `.env` for Docker Compose (CI-safe defaults).
2. Starts the stack with `docker compose up -d --wait`.
3. Waits for the API `GET /healthz` endpoint.
4. Runs Alembic migrations inside the API container.
5. Waits for the API `GET /readyz` endpoint, printing truncated diagnostics every ~30s.
6. Installs web dependencies with `npm ci`.
7. Installs Playwright packages ephemerally (`npm i -D --no-save --no-package-lock`).
8. Runs Playwright tests with `PW_CHANNEL=chrome` and `PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1`.
9. Uploads the Playwright HTML report as an artifact.
10. Tears down the compose stack and cleans up the `.env` file.

## Local reproduction (optional)

```bash
# From repo root
cat > .env <<'ENV'
APP_ENV=dev
TESTING=true
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_DB=cleaning
DATABASE_URL=postgresql+psycopg://postgres:postgres@db:5432/cleaning
NEXT_PUBLIC_API_BASE_URL=http://api:8000
ENV

docker compose -f docker-compose.yml -f docker-compose.ci.yml up -d --wait db redis api web

# Verify health
curl -f http://localhost:8000/healthz
docker compose -f docker-compose.yml -f docker-compose.ci.yml exec -T api alembic upgrade head
curl -f http://localhost:8000/readyz

cd web
npm ci
PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 npm i -D --no-save --no-package-lock @playwright/test playwright
PW_CHANNEL=chrome PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 npx playwright test --config=../e2e/playwright.config.ts --reporter=html

# Cleanup
cd ..
docker compose -f docker-compose.yml -f docker-compose.ci.yml down -v
rm -f .env
```
