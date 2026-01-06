# Release Checklist

Use this checklist to gate releases before promoting a commit to staging or production. Treat every unchecked box as a hard stop.

## Go/No-Go Checks
- [ ] CI pipeline green (API lint/tests, Web typecheck/build)
- [ ] Release candidate tagged or commit SHA recorded
- [ ] Database migrations reviewed and safe to run

## Pre-Deploy Validation
- [ ] Run backend unit tests locally if changes touch API logic: `cd backend && pytest -v -m "not smoke and not postgres"`
- [ ] Verify web build locally when UI changed: `cd web && npm install && npm run build`
- [ ] Confirm environment variables for target environment are present and non-default

## Smoke Tests
- [ ] Run end-to-end smoke script from repo root: `./scripts/smoke.sh`
- [ ] API readiness endpoint healthy: `curl -fsS "$API_BASE_URL/readyz"`
- [ ] Web root returns 200: `curl -fsS "$WEB_BASE_URL/"`

## Sign-off
- [ ] Deployment owner confirms rollback plan and monitoring in place
- [ ] Approver acknowledges Go/No-Go decision
