# E2E CI (Playwright) — Local Run Guide

This repo runs Playwright E2E with Docker Compose and ephemeral Playwright deps.

> Note: `web/vitest.config.ts` is excluded from Next.js typechecking in production builds,
> so Vitest is not required for the Docker image.

## Local run (mirrors CI)

```bash
ADMIN_BASIC_USERNAME=e2e ADMIN_BASIC_PASSWORD=pass \
ADMIN_PROXY_AUTH_ENABLED=true TRUST_PROXY_HEADERS=true TRUSTED_PROXY_IPS=127.0.0.1 \
E2E_PROXY_AUTH_ENABLED=true E2E_PROXY_AUTH_SECRET=local-dev-secret \
docker compose -f docker-compose.yml -f docker-compose.e2e.yml up -d --wait

cd web
npm ci
npm i -D --no-save --no-package-lock @playwright/test playwright

PLAYWRIGHT_BASE_URL=http://127.0.0.1:3000 \
PLAYWRIGHT_API_BASE_URL=http://127.0.0.1:8000 \
ADMIN_BASIC_USERNAME=e2e \
ADMIN_BASIC_PASSWORD=pass \
ADMIN_PROXY_AUTH_ENABLED=true \
E2E_PROXY_AUTH_ENABLED=true \
E2E_PROXY_AUTH_SECRET=local-dev-secret \
PW_CHANNEL=chrome \
PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 \
npx playwright test --config e2e/playwright.config.ts
```

## Proxy-auth mode notes

When `ADMIN_PROXY_AUTH_ENABLED=true`, Basic Auth against `/v1/admin/*` is blocked. E2E uses
HMAC-signed proxy headers (`E2E_PROXY_AUTH_ENABLED=true`) to simulate reverse-proxy injected
headers for admin endpoints. Keep the secret local or injected at runtime in CI; never commit it.

## Cleanup

```bash
docker compose -f docker-compose.yml -f docker-compose.e2e.yml down -v
```
