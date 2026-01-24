# E2E CI - Playwright Tests in GitHub Actions

## Overview
The E2E CI workflow runs Playwright tests against the full application stack in an ephemeral Docker Compose environment. It validates critical user flows without modifying package manifests.

## Workflow: `.github/workflows/e2e.yml`

### Triggers
- Pull requests to `main`
- Pushes to `main`

### Architecture
The workflow orchestrates:
1. **Docker Compose stack** (db, redis, api, web) via `docker-compose.yml` + `docker-compose.ci.yml`
2. **Ephemeral Playwright installation** (no `package.json` changes)
3. **Chrome-based E2E tests** from `e2e/` directory
4. **Artifact uploads** (test reports, failure logs)

## Workflow Steps

### 1. Environment Setup
- **Checkout code** with `actions/checkout@v4`
- **Node.js setup** using `.nvmrc` version
- **Create CI `.env`** with test credentials (postgres, API URLs)

### 2. Stack Orchestration
```bash
docker compose -f docker-compose.yml -f docker-compose.ci.yml up -d --wait db redis api web
```

**Health checks:**
- API: polls `http://localhost:8000/healthz` (60s timeout)
- Web: polls `http://localhost:3000` (60s timeout)

If health checks fail, the workflow dumps service logs and exits.

### 3. Playwright Installation (Ephemeral)
```bash
cd web
npm ci                                                      # Install web deps
npm i -D --no-save --no-package-lock @playwright/test playwright  # Ephemeral Playwright
```

**Why ephemeral?**
- Keeps `package.json` and `package-lock.json` clean
- Prevents CI-only deps from polluting the project
- Uses `--no-save` and `--no-package-lock` flags

### 4. Test Execution
```bash
cd e2e
PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 \
PW_CHANNEL=chrome \
PLAYWRIGHT_BASE_URL=http://localhost:3000 \
PLAYWRIGHT_API_BASE_URL=http://localhost:8000 \
ADMIN_BASIC_USERNAME=admin \
ADMIN_BASIC_PASSWORD=admin123 \
npx --prefix ../web playwright test --config=playwright.config.ts
```

**Environment variables:**
- `PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1`: Use Chrome from GitHub Actions runner
- `PW_CHANNEL=chrome`: Force Chrome (not Chromium)
- `PLAYWRIGHT_BASE_URL`: Web UI endpoint
- `PLAYWRIGHT_API_BASE_URL`: API endpoint
- `ADMIN_BASIC_USERNAME/PASSWORD`: Admin credentials for auth tests

**Test location:** `e2e/tests/`
- `admin-critical.spec.ts`: Admin UI critical flows
- `public-booking.spec.ts`: Public booking estimate flow

### 5. Artifact Uploads
**Always uploaded (on success or failure):**
- `playwright-report/`: HTML report, traces, screenshots, videos
- `test-results/`: Raw test results

**On failure only:**
- `compose-e2e.log`: Full Docker Compose logs
- `compose-ps-e2e.txt`: Container status snapshot

**Retention:** 7 days

### 6. Teardown
```bash
docker compose -f docker-compose.yml -f docker-compose.ci.yml down -v
rm -f .env
```

**Manifest verification:**
```bash
git diff --exit-code web/package.json web/package-lock.json
```
If package files changed, the workflow fails (ephemeral install leaked).

## Stabilization Features

### Retries
- **Playwright retries:** Configured in `e2e/playwright.config.ts` (`retries: process.env.CI ? 1 : 0`)
- **Health check retries:** 60s timeout with 2s polling interval

### Timeouts
- **Job timeout:** 15 minutes
- **Health checks:** 60s per service (API, Web)
- **Playwright test timeout:** 60s (configured in `playwright.config.ts`)
- **Playwright expect timeout:** 10s

### Failure Handling
- Logs are captured on failure (compose logs, container status)
- Playwright reports are always uploaded (traces, screenshots, videos on failure)

## Configuration Files

### `e2e/playwright.config.ts`
- **Test directory:** `./tests`
- **Timeouts:** 60s test, 10s expect
- **Parallelization:** `fullyParallel: true`
- **Retries:** 1 retry in CI, 0 locally
- **Reporters:** `list` (console output)
- **Trace/Screenshot/Video:** Retained on failure

### `docker-compose.ci.yml`
Overrides for CI:
- Exposes ports: `api:8000`, `web:3000`
- Sets `NEXT_PUBLIC_API_BASE_URL=http://api:8000` (internal Docker network)

## Debugging Failures

### View Playwright Report
1. Download `playwright-report` artifact from GitHub Actions
2. Unzip and open `index.html` in a browser
3. View traces, screenshots, and videos for failed tests

### View Compose Logs
1. Download `compose-e2e-logs` artifact (only on failure)
2. Review `compose-e2e.log` for service errors
3. Check `compose-ps-e2e.txt` for container status

### Local Reproduction
Follow [docs/E2E_LOCAL.md](./E2E_LOCAL.md) to run tests locally against `docker compose up` stack.

## Acceptance Criteria (Met)
- ✅ E2E workflow runs on `main` branch
- ✅ Playwright reports uploaded as artifacts (7-day retention)
- ✅ No package manifest changes (ephemeral install verified)
- ✅ Health checks with retries/timeouts (60s per service)
- ✅ Full stack orchestration (db, redis, api, web)
- ✅ Chrome-based tests via `PW_CHANNEL=chrome`
- ✅ Logs captured on failure (compose + Playwright artifacts)

## Related Documentation
- [E2E_LOCAL.md](./E2E_LOCAL.md): Local E2E setup and manual testing
- [CI workflow](./.github/workflows/ci.yml): Main CI pipeline (unit tests, builds, security scans)
