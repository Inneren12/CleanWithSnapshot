# Web Testing in CI (Vitest)

This repo runs a soft-gated Vitest coverage job in CI without committing additional
JavaScript test dependencies to `package.json`. The CI workflow installs ephemeral
deps only for the job, runs coverage, and uploads the `coverage/` directory as an
artifact for inspection.

## CI job outline

The `Web - Vitest (Coverage, Soft Gate)` job in `.github/workflows/ci.yml` performs:

1. `cd web`
2. `npm ci`
3. `npm install --no-save vitest @testing-library/react @testing-library/jest-dom jsdom`
4. `npx vitest run --coverage` (soft gate via `continue-on-error`)
5. Uploads `web/coverage/` as the `vitest-coverage` artifact

## Notes

- Coverage thresholds are intentionally soft at first; failures do not block CI.
- No package manifests are changed because all test tooling is installed
  ephemerally for the CI job only.
