# Local Playwright E2E (web)

## Prerequisites
- Local stack running:
  - Web UI at `http://localhost:3000`.
  - API at `http://localhost:8000`.
- Admin Basic Auth configured (defaults shown below).
- For the public booking flow, ensure the chat + slots endpoints are available. The test only verifies the estimate + booking details UI (no lead submission).

## Environment variables
The tests read these variables (defaults shown):

```bash
export PLAYWRIGHT_BASE_URL="http://localhost:3000"
export PLAYWRIGHT_API_BASE_URL="http://localhost:8000"
export ADMIN_BASIC_USERNAME="admin"
export ADMIN_BASIC_PASSWORD="admin123"
```

## Install Playwright (ephemeral)
> Do not change `package.json` or `package-lock.json`.

```bash
cd web
npm i -D --no-save --no-package-lock @playwright/test playwright
```

## Run tests
```bash
PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 PW_CHANNEL=chrome npx playwright test
```

## Notes
- The admin E2E verifies credentials via `/v1/admin/profile` and seeds local storage for the UI.
- The public booking E2E sends a sample message (`2 bed 1 bath standard cleaning`) and asserts that the estimate and booking detail panel are visible.
