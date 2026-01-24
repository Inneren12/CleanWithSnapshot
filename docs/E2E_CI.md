# E2E CI (Playwright) — Local Run Guide

This repo runs Playwright E2E with Docker Compose and ephemeral Playwright deps.

> Note: `web/vitest.config.ts` is excluded from Next.js typechecking in production builds,
> so Vitest is not required for the Docker image.

## Local run (mirrors CI)

```bash
ADMIN_BASIC_USERNAME=e2e ADMIN_BASIC_PASSWORD=pass \
docker compose -f docker-compose.yml -f docker-compose.e2e.yml up -d --wait

cd web
npm ci
npm i -D --no-save --no-package-lock @playwright/test playwright

PLAYWRIGHT_BASE_URL=http://127.0.0.1:3000 \
PLAYWRIGHT_API_BASE_URL=http://127.0.0.1:8000 \
ADMIN_BASIC_USERNAME=e2e \
ADMIN_BASIC_PASSWORD=pass \
PW_CHANNEL=chrome \
PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 \
npx playwright test --config e2e/playwright.config.ts
```

## Cleanup

```bash
docker compose -f docker-compose.yml -f docker-compose.e2e.yml down -v
```
