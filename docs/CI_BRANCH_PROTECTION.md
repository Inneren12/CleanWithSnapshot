# CI Branch Protection

This document describes the GitHub branch protection rules enforced for `main` and how the corresponding status checks map to the CI workflow defined in `.github/workflows/ci.yml`. Keep this file in sync with the workflow job names so the required checks match the exact statuses GitHub reports.

## Required Status Checks

The following checks must complete successfully before merges to `main`:

- **API - Build & Test**: Runs in the `api` job and performs Python dependency installation, a syntax-only Ruff pass (`ruff check app tests --select E9`), and pytest unit tests (`pytest -v -m "not smoke and not postgres" --ignore=tests/smoke --tb=short`).
- **Web - Build**: Runs in the `web` job and ensures the frontend passes TypeScript compilation (`npx tsc --noEmit`), optional linting (`npm run lint --if-present`), and a production build (`npm run build`).
- **API - Prod Config Validation**: Validates that production-only settings still parse and enforce required secrets using the `api-prod-config` job.
- **Infrastructure - Validation**: Verifies `docker-compose.yml` syntax and bash script validity inside the `infra` job.

Make sure any updates to `.github/workflows/ci.yml` keep these `name:` values unchanged or update this list accordingly so branch protection stays accurate.

## PR Hygiene Expectations

- Keep pull requests small enough that the API and Web checks finish reliably within GitHub's time limits.
- Avoid disabling or renaming jobs unless coordinating a branch protection update.
- Treat red builds as a stop sign: rerun only after addressing failures.

## Troubleshooting Tips

- **Cache misses**: Dependency caches are keyed on `requirements.txt`/`constraints.txt` for backend and `package-lock.json` for frontend. After cache misses, expect slightly longer runtimes.
- **Syntax guard failures**: An E9 failure usually indicates a syntax error preventing test collection. Fix the syntax before rerunning tests locally with `ruff check app tests --select E9`.
- **TypeScript failures**: For quick iterations, run `npm ci && npx tsc --noEmit` in `web/` to match the CI check locally.

If a check is flaky or consistently failing, surface the issue in the next engineering sync so branch protection remains meaningful.
