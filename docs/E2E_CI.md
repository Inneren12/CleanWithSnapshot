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
2. **Ephemeral Playwright installation** in `web/` (no `package.json` changes)
3. **Chrome-based E2E tests** from `web/e2e/` directory
4. **Artifact uploads** (test reports, failure logs)

### Module Resolution
Playwright is installed ephemerally in `web/node_modules/@playwright/test`, and tests are located in `web/e2e/`. This ensures Node.js module resolution works correctly: when `web/e2e/playwright.config.ts` imports `@playwright/test`, Node finds it in the nearest `node_modules/` (at `web/node_modules/`).

### Production Build Isolation
The `web/e2e/` directory is excluded from the production web Docker build:

**TypeScript exclusion** (`web/tsconfig.json`):
```json
"exclude": ["node_modules", "e2e"]
```
This prevents Next.js build from typechecking `e2e/playwright.config.ts`, which would fail because `@playwright/test` is not installed in production.

**Docker build exclusion** (`web/.dockerignore`):
```
e2e/
**/*.spec.ts
**/*.spec.tsx
playwright.config.*
```
This prevents E2E test files from being copied into the production Docker image, reducing image size and avoiding build-time errors.

**Why this matters:**
- Production builds run `npm ci` (production deps only) then `npm run build`
- If TypeScript tried to check `e2e/playwright.config.ts`, it would error: `Cannot find module '@playwright/test'`
- E2E tests run in CI on the GitHub Actions runner filesystem, not inside the Docker container
- The running web service never needs test files

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

**Module resolution verification:**
```bash
cd web
node -e "require.resolve('@playwright/test')"  # Ensures @playwright/test is resolvable
```

This step verifies that `@playwright/test` can be resolved from the `web/` directory, preventing the "Cannot find module '@playwright/test'" error.

### 4. Test Execution
```bash
cd web
PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 \
PW_CHANNEL=chrome \
PLAYWRIGHT_BASE_URL=http://localhost:3000 \
PLAYWRIGHT_API_BASE_URL=http://localhost:8000 \
ADMIN_BASIC_USERNAME=admin \
ADMIN_BASIC_PASSWORD=admin123 \
npx playwright test --config e2e/playwright.config.ts
```

**Environment variables:**
- `PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1`: Use Chrome from GitHub Actions runner
- `PW_CHANNEL=chrome`: Force Chrome (not Chromium)
- `PLAYWRIGHT_BASE_URL`: Web UI endpoint
- `PLAYWRIGHT_API_BASE_URL`: API endpoint
- `ADMIN_BASIC_USERNAME/PASSWORD`: Admin credentials for auth tests

**Test location:** `web/e2e/tests/`
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
- **Playwright retries:** Configured in `web/e2e/playwright.config.ts` (`retries: process.env.CI ? 1 : 0`)
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

### `web/e2e/playwright.config.ts`
- **Test directory:** `./tests` (relative to config location: `web/e2e/tests/`)
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
- ✅ Module resolution fixed: `@playwright/test` resolves correctly from `web/e2e/`
- ✅ Production build isolation: `e2e/` excluded from TypeScript and Docker build

## Troubleshooting

### "Cannot find module '@playwright/test'" Error
**Symptom:** CI fails with `Cannot find module '@playwright/test'` when loading config.

**Root cause:** Node.js module resolution looks for `node_modules` starting from the config file location and walking up. If Playwright is installed in `web/node_modules` but config is in a sibling directory (e.g., `/e2e`), Node won't find it.

**Solution:** E2E tests are located in `web/e2e/`, sharing the same `node_modules` where Playwright is installed. Tests run from `web/` directory with `--config e2e/playwright.config.ts`.

**Verification:**
```bash
cd web
node -e "require.resolve('@playwright/test')"  # Should succeed
```

### "Type error: Cannot find module '@playwright/test'" During Web Build
**Symptom:** Docker build or `npm run build` fails with TypeScript error in `e2e/playwright.config.ts`.

**Root cause:** Next.js build typechecks all `**/*.ts` files by default. If `e2e/playwright.config.ts` is included, TypeScript tries to resolve `@playwright/test`, which isn't installed in production builds (and shouldn't be).

**Solution:** Exclude `e2e/` from both TypeScript and Docker build:

1. **TypeScript exclusion** (`web/tsconfig.json`):
   ```json
   "exclude": ["node_modules", "e2e"]
   ```

2. **Docker build exclusion** (`web/.dockerignore`):
   ```
   e2e/
   **/*.spec.ts
   playwright.config.*
   ```

**Why this works:** E2E tests run on CI runner filesystem, not inside Docker containers. The production web image doesn't need test files, and excluding them prevents TypeScript from checking files that import dev-only dependencies.

## Related Documentation
- [E2E_LOCAL.md](./E2E_LOCAL.md): Local E2E setup and manual testing
- [CI workflow](./.github/workflows/ci.yml): Main CI pipeline (unit tests, builds, security scans)
