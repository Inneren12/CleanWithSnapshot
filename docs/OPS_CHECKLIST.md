# After-deploy checklist

Use the one-command script to run the full verification checklist after deploys. It relies on `/etc/cleaning/cleaning.env` and does not print secret values.

## Run

```bash
./ops/after_deploy_check.sh
```

## What it checks

- Env audit via `ops/env_audit.py`.
- Container status via `docker compose ps`.
- API `/healthz` and `/readyz`.
- Web root headers for the primary web domain.
- Admin Basic Auth access to `/v1/admin/whoami`.
- Job heartbeat summary parsed from `/readyz`.
- Upload root write test inside the API container.
- Smoke checks via `./ops/smoke.sh`.

## Optional helper

Validate the Caddyfile configuration from the repo:

```bash
./ops/validate_caddyfile.sh
```

## Design tokens

If `design/tokens.json` changes, run the token build helper before opening a PR:

```bash
./ops/build_tokens.sh
```
