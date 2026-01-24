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

### Ephemeral Admin Credentials (No Secrets Required)

The E2E workflow generates **ephemeral admin credentials at runtime** and injects them into the stack. This approach:
- ✅ Works for PRs from forks (GitHub doesn't pass secrets to fork PRs)
- ✅ Requires zero configuration (no secrets to set up)
- ✅ Credentials exist only during CI run (never committed or logged)
- ✅ New random password generated for each test run

**How it works:**

1. **Generation** (after checkout):
   ```bash
   ADMIN_BASIC_USERNAME=e2e-admin
   ADMIN_BASIC_PASSWORD=$(openssl rand -base64 24)  # Random 24-char password
   ```

2. **Injection** (via `docker-compose.e2e.yml` override):
   ```yaml
   services:
     api:
       environment:
         ADMIN_BASIC_USERNAME: ${ADMIN_BASIC_USERNAME}
         ADMIN_BASIC_PASSWORD: ${ADMIN_BASIC_PASSWORD}
   ```

3. **Verification** (before Playwright tests):
   ```bash
   curl -u "$ADMIN_BASIC_USERNAME:$ADMIN_BASIC_PASSWORD" \
     http://localhost:8000/v1/admin/profile
   ```
   If this fails, the workflow stops before running E2E tests.

4. **Playwright tests** receive the same credentials via environment variables:
   ```yaml
   env:
     ADMIN_BASIC_USERNAME: ${{ env.ADMIN_BASIC_USERNAME }}
     ADMIN_BASIC_PASSWORD: ${{ env.ADMIN_BASIC_PASSWORD }}
   ```

**Security notes:**
- Credentials are **never logged** (sanity check uses `-fsS` curl flags)
- Credentials are **not in artifacts** (only in runner environment)
- Each CI run uses a **different random password**
- Credentials are **scoped to the CI job** (cleared after teardown)

**Why no GitHub Secrets?**
GitHub doesn't pass repository secrets to workflows triggered by PRs from forks (security measure). Using runtime-generated credentials ensures E2E tests work for **all PRs**, including external contributions.

### Deterministic E2E Mode (Public Booking Test)

The E2E workflow enables **`NEXT_PUBLIC_E2E_MODE=true`** for the web service to make public booking tests deterministic and fast:

**Problem it solves:**
- Public booking flow relies on chat/bot API which may be unavailable, slow, or non-deterministic in CI
- External integrations, seed data, or timing issues can cause test flakiness
- Real bot responses require backend services and can fail due to network/rate limits

**How it works:**

When `NEXT_PUBLIC_E2E_MODE=true`:
1. User submits chat message (e.g., "2 bed 1 bath standard cleaning")
2. **Bypasses API call** to `/v1/chat/turn` entirely
3. **Injects deterministic bot message** after 500ms delay:
   ```
   "Your estimate is ready! Based on your 2 bed 1 bath standard cleaning..."
   ```
4. **Sets deterministic estimate**:
   ```json
   {
     "rate": 35,
     "team_size": 2,
     "time_on_site_hours": 3.0,
     "total_before_tax": 105.0,
     ...
   }
   ```
5. Triggers "Ready to book" UI state (pill appears, booking form shown)

**Where it's enabled:**
- `docker-compose.e2e.yml` sets `NEXT_PUBLIC_E2E_MODE: "true"` for web service
- **Only used in CI** (not in production, not in docker-compose.yml)

**Test verification:**
- Test checks for `data-testid="e2e-mode-on"` (hidden div) to ensure mode is active
- Bot message appears within ~10s (much faster than real API: ~30s)
- "Ready to book" pill appears within ~5s

**Production safety:**
- Normal production behavior unchanged (env var not set)
- E2E mode code gated behind `if (process.env.NEXT_PUBLIC_E2E_MODE === 'true')`
- Mode indicator hidden from users (display: none, aria-hidden)

**Running locally with ephemeral credentials:**
```bash
# Set ephemeral admin credentials
export ADMIN_BASIC_USERNAME=e2e-local
export ADMIN_BASIC_PASSWORD=test123

# Start stack with E2E override
docker compose -f docker-compose.yml -f docker-compose.e2e.yml up -d

# Verify admin auth works
curl -u "e2e-local:test123" http://localhost:8000/v1/admin/profile

# Run E2E tests (from web/ directory)
cd web
npm ci
npm i -D --no-save --no-package-lock @playwright/test playwright
PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 \
PW_CHANNEL=chrome \
PLAYWRIGHT_BASE_URL=http://localhost:3000 \
PLAYWRIGHT_API_BASE_URL=http://localhost:8000 \
ADMIN_BASIC_USERNAME=e2e-local \
ADMIN_BASIC_PASSWORD=test123 \
npx playwright test --config e2e/playwright.config.ts
```

### Test Selector Strategy

E2E tests use **stable selectors** to avoid brittle failures:

**Preferred selectors (in order):**
1. `data-testid` attributes for E2E landmarks
2. Role-based selectors (`getByRole`)
3. Text-based selectors for unique text
4. Avoid: CSS class selectors (`.messages .message.bot`)

**Test IDs added for E2E:**
- `data-testid="booking-chat"`: Chat window container
- `data-testid="chat-messages"`: Messages list
- `data-testid="bot-message"`: Bot message bubbles
- `data-testid="user-message"`: User message bubbles
- `data-testid="ready-to-book-pill"`: Ready to book indicator

**Timeouts:**
- Bot message appearance: 30s (CI can be slow, chat requires API call)
- "Ready to book" pill: 30s (estimate calculation + UI update)
- Booking details heading: 10s (DOM element, no network)

## Workflow Steps

### 1. Environment Setup
- **Checkout code** with `actions/checkout@v4`
- **Node.js setup** using `.nvmrc` version
- **Create CI `.env`** with test credentials (postgres, API URLs)
- **Generate ephemeral admin credentials** (random 24-char password, username=`e2e-admin`)

### 2. Stack Orchestration
```bash
docker compose -f docker-compose.yml -f docker-compose.ci.yml -f docker-compose.e2e.yml up -d --wait db redis api web
```

**Compose overrides:**
- `docker-compose.yml`: Base stack (db, redis, api, web, jobs, caddy)
- `docker-compose.ci.yml`: CI ports and API URL overrides
- `docker-compose.e2e.yml`: **Ephemeral admin credentials injection** (only for E2E)

**Health checks:**
- API: polls `http://localhost:8000/healthz` (60s timeout)
- Web: polls `http://localhost:3000` (60s timeout)
- **Admin auth:** verifies ephemeral credentials work via `GET /v1/admin/profile`

If health checks or admin auth verification fail, the workflow dumps service logs and exits.

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
npx playwright test --config e2e/playwright.config.ts
```

**Environment variables:**
- `PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1`: Use Chrome from GitHub Actions runner
- `PW_CHANNEL=chrome`: Force Chrome (not Chromium)
- `PLAYWRIGHT_BASE_URL`: Web UI endpoint
- `PLAYWRIGHT_API_BASE_URL`: API endpoint
- `ADMIN_BASIC_USERNAME`: Ephemeral admin username (generated at runtime: `e2e-admin`)
- `ADMIN_BASIC_PASSWORD`: Ephemeral admin password (random 24-char string per run)

**Note:** Admin credentials are passed from the CI environment (generated earlier in the workflow), not hardcoded. This ensures tests work even for PRs from forks where GitHub Secrets are unavailable.

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
- Playwright reports are always uploaded (screenshots on failure)
- **Note:** Video and trace are disabled to avoid ffmpeg dependency when using `PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1`

## Configuration Files

### `web/e2e/playwright.config.ts`
- **Test directory:** `./tests` (relative to config location: `web/e2e/tests/`)
- **Timeouts:** 60s test, 10s expect
- **Parallelization:** `fullyParallel: true`
- **Retries:** 1 retry in CI, 0 locally
- **Reporters:** `list` (console output)
- **Browser:** System Chrome via `PW_CHANNEL=chrome` (headless mode)
- **Screenshot:** `only-on-failure` (saved to test-results)
- **Video:** `off` (disabled to avoid ffmpeg dependency)
- **Trace:** `off` (disabled to avoid ffmpeg dependency)
- **Launch options:** `--no-sandbox`, `--disable-setuid-sandbox` (required for CI)

**Why video/trace are disabled:**
When using `PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1`, Playwright doesn't download its bundled browsers or ffmpeg. Video recording requires ffmpeg, so it must be disabled. Traces may also require ffmpeg in some configurations. Screenshots are retained as they don't require additional dependencies.

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
- ✅ Chrome-based tests via `PW_CHANNEL=chrome` (system Chrome, no downloads)
- ✅ Logs captured on failure (compose + Playwright artifacts)
- ✅ Module resolution fixed: `@playwright/test` resolves correctly from `web/e2e/`
- ✅ Production build isolation: `e2e/` excluded from TypeScript and Docker build
- ✅ No browser/ffmpeg downloads: video/trace disabled, tests run with `PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1`
- ✅ **Ephemeral admin credentials**: Generated at runtime (no GitHub Secrets, works for fork PRs)
- ✅ **Admin auth verification**: Pre-flight check before Playwright tests
- ✅ **Deterministic E2E mode**: Public booking test uses `NEXT_PUBLIC_E2E_MODE=true` (bypasses chat API, fast bot responses)
- ✅ Stable selectors: `data-testid` attributes for key E2E landmarks
- ✅ Resilient timeouts: 10s for E2E mode bot responses, 5s for estimate pill

## Troubleshooting

### "Admin auth failed (401)" Error
**Symptom:** Admin E2E test fails with error:
```
Admin auth failed (401): {"detail":"Invalid authentication"}
at helpers/adminAuth.ts:30
```

**Root cause:** The ephemeral admin credentials were not injected correctly into the API service, or the API is not configured to use them.

**Solution:**

1. **Check the "Verify admin auth works" step in CI:**
   - This step runs before Playwright tests and should pass
   - If it fails, the problem is with credential injection, not Playwright
   - Review logs from this step to see the curl response

2. **Verify `docker-compose.e2e.yml` is being used:**
   - Workflow should use: `-f docker-compose.yml -f docker-compose.ci.yml -f docker-compose.e2e.yml`
   - This override injects `ADMIN_BASIC_USERNAME` and `ADMIN_BASIC_PASSWORD` into the API

3. **Check if API is reading the environment variables:**
   - API must read admin credentials from `ADMIN_BASIC_USERNAME` and `ADMIN_BASIC_PASSWORD`
   - Check API logs: `docker compose logs api` (credentials should NOT be logged)
   - Verify API code reads these env vars for BasicAuth validation

4. **Test locally with ephemeral credentials:**
   ```bash
   export ADMIN_BASIC_USERNAME=e2e-local
   export ADMIN_BASIC_PASSWORD=test123
   docker compose -f docker-compose.yml -f docker-compose.e2e.yml up -d
   curl -u "e2e-local:test123" http://localhost:8000/v1/admin/profile
   ```
   Should return 200 with admin profile data.

5. **Check if credentials are missing (better error):**
   If environment variables are not set, you'll get:
   ```
   E2E admin credentials not configured. Set ADMIN_BASIC_USERNAME and ADMIN_BASIC_PASSWORD environment variables.
   ```

**Prevention:** Ensure `docker-compose.e2e.yml` is used in all compose commands during E2E workflow.

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

### "Executable doesn't exist ... ffmpeg" Error
**Symptom:** Playwright fails with error about missing ffmpeg executable when using `PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1`.

**Root cause:** Video recording and some trace features require ffmpeg, which is bundled with Playwright's browser downloads. When `PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1` is set, ffmpeg is not downloaded. Attempting to record video or traces will fail.

**Solution:** Disable features that require ffmpeg in `web/e2e/playwright.config.ts`:

```typescript
use: {
  video: 'off',           // Disable video recording
  trace: 'off',           // Disable trace (or use carefully)
  screenshot: 'only-on-failure',  // Screenshots work without ffmpeg
  channel: 'chrome',      // Use system Chrome
  headless: true,
  launchOptions: {
    args: ['--no-sandbox', '--disable-setuid-sandbox'],
  },
}
```

**Why this works:**
- CI uses system Chrome from GitHub Actions runner (no download needed)
- Screenshots don't require ffmpeg
- Video and trace are disabled to avoid ffmpeg dependency
- Tests run successfully with `PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1` and `PW_CHANNEL=chrome`

**Trade-off:** You lose video recordings and detailed traces for debugging, but still get screenshots on failure and test results. This is acceptable for CI where we prioritize speed and minimal dependencies.

### "element(s) not found" / Selector Timeout Errors
**Symptom:** Public booking test fails with:
```
expect(locator('.messages .message.bot').first()).toBeVisible() failed
element(s) not found
```

**Root cause:** One of:
1. Brittle CSS selectors broke due to UI changes
2. Bot response timing out or not appearing
3. CI slowness causing timeouts with default wait times

**Solution:**

1. **Use stable selectors (testids):** Tests now use `data-testid` attributes:
   ```typescript
   // Bad (brittle):
   page.locator('.messages .message.bot')

   // Good (stable):
   page.getByTestId('bot-message')
   ```

2. **Increase timeouts for slow CI:**
   ```typescript
   await expect(page.getByTestId('bot-message').first()).toBeVisible({
     timeout: 30000,  // 30s for bot response
   });
   ```

3. **Check if chat endpoint is working:**
   ```bash
   curl http://localhost:8000/v1/chat/turn -X POST \
     -H "Content-Type: application/json" \
     -d '{"session_id":"test","message":"2 bed 1 bath","brand":"economy","channel":"web"}'
   ```
   Should return bot reply and estimate.

4. **Review screenshots in artifacts:**
   - Download `playwright-report` artifact
   - Check screenshot at failure point
   - Verify UI reached expected state

**Prevention:**
- Always use `data-testid` for E2E landmarks
- Set appropriate timeouts based on operation (30s for API calls, 10s for DOM)
- Keep selectors simple and stable

### "Bot message never appears" / Public Booking Test Timeout
**Symptom:** Public booking test times out waiting for bot message:
```
expect(page.getByTestId('bot-message').first()).toBeVisible() timeout
```

**Root cause:** One of:
1. E2E deterministic mode not enabled (`NEXT_PUBLIC_E2E_MODE` not set)
2. `docker-compose.e2e.yml` not used when starting web service
3. Web service didn't rebuild with new env var

**Solution:**

1. **Verify E2E mode is enabled:**
   - Test should check `data-testid="e2e-mode-on"` exists
   - If this assertion fails, E2E mode is not active
   - Check workflow uses all three compose files:
     ```bash
     docker compose -f docker-compose.yml -f docker-compose.ci.yml -f docker-compose.e2e.yml up -d
     ```

2. **Check docker-compose.e2e.yml includes web env:**
   ```yaml
   services:
     web:
       environment:
         NEXT_PUBLIC_E2E_MODE: "true"
   ```

3. **Verify web container sees the env var:**
   ```bash
   docker compose exec web env | grep E2E_MODE
   # Should show: NEXT_PUBLIC_E2E_MODE=true
   ```

4. **Test locally with E2E mode:**
   ```bash
   docker compose -f docker-compose.yml -f docker-compose.e2e.yml up -d
   # Visit http://localhost:3000
   # Open browser console: document.querySelector('[data-testid="e2e-mode-on"]')
   # Should return hidden div element
   ```

5. **Check browser console for errors:**
   - E2E mode code might be throwing JavaScript errors
   - Check page.tsx submitMessage E2E conditional branch

**Expected behavior with E2E mode:**
- Bot message appears within ~1 second (500ms + render)
- "Ready to book" pill appears immediately after
- No network calls to `/v1/chat/turn`
- Test completes in ~10 seconds total

**Prevention:**
- Always verify `e2e-mode-on` testid at start of test
- Use `docker-compose.e2e.yml` consistently in all CI steps
- Keep E2E mode logic simple and side-effect free

## Related Documentation
- [E2E_LOCAL.md](./E2E_LOCAL.md): Local E2E setup and manual testing
- [CI workflow](./.github/workflows/ci.yml): Main CI pipeline (unit tests, builds, security scans)
