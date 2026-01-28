# Web Testing in CI (Vitest)

This repo runs a hard-gated Vitest coverage job in CI without committing additional
JavaScript test dependencies to `package.json`. The CI workflow installs ephemeral
deps only for the job, runs coverage, and uploads the `coverage/` directory as an
artifact for inspection.

## CI job outline

The `Web - Vitest (Coverage)` job in `.github/workflows/ci.yml` performs:

1. `cd web`
2. `npm ci`
3. `npm install --no-save vitest @testing-library/react @testing-library/jest-dom jsdom`
4. `npx vitest run --coverage` (hard gate; failures fail CI)
5. Uploads `web/coverage/` as the `vitest-coverage` artifact

## Notes

- Vitest failures now block merges, so keep the tests deterministic and stable.
- No package manifests are changed because all test tooling is installed
  ephemerally for the CI job only.

## Run locally

```bash
cd web
npm i -D --no-save --no-package-lock vitest @testing-library/react @testing-library/jest-dom jsdom
TZ=UTC CI=true NODE_ENV=test npx vitest run
```
