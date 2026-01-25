# Rollback Runbook (One-Command)

This runbook documents the deterministic rollback flow for CleanWithSnapshot.

## Default target (last known good)

`./ops/deploy.sh` and `./ops/blue-green-deploy.sh` write a deployment state file at:

```
/opt/cleaning/.deploy_state.json
```

It stores:

- `last_good_sha` — last successful deploy commit.
- `last_good_timestamp` — UTC time of successful deploy.
- `db_revision` — DB migration revision recorded at deploy time.
- `expected_heads` — target Alembic heads from the deployed code.
- `deploy_mode` / `deploy_color` — `standard` or `blue-green`, plus the active color.

`./ops/rollback.sh` uses this file by default if no explicit SHA or tag is provided.

## Commands

Rollback to last known good:

```bash
cd /opt/cleaning
./ops/rollback.sh
```

Rollback to a specific SHA:

```bash
./ops/rollback.sh --sha <sha>
```

Rollback to a specific tag:

```bash
./ops/rollback.sh --tag <tag>
```

Dry-run (print commands only):

```bash
./ops/rollback.sh --dry-run
```

Verify-only (no changes, just health + routing checks):

```bash
./ops/rollback.sh --verify-only
```

## Database migration safety (forward-only)

Rollback **never** downgrades the database schema. The script compares:

- Current DB revision (via `alembic_version` in Postgres).
- Target code revision heads (via Alembic script metadata).

If the DB revision is not compatible with the target code:

1. Rollback is **refused** by default.
2. You must pass **both** flags to proceed:

```bash
./ops/rollback.sh --allow-db-ahead --i-accept-forward-only-db
```

This ensures operators explicitly acknowledge the risk of running older code against newer schema.

## Health verification

After rollback, the script verifies:

- `GET /healthz` → OK
- `GET /readyz` → OK and `migrations_current=true`
- `ops/smoke.sh` (web + API checks)

On failure, it prints diagnostics (`docker compose ps` + log tail) and leaves containers running for debugging.

## Caddy routing + canary safety

- Standard rollback reuses the main `Caddyfile` and verifies API/Web through the public endpoints.
- If a canary is active (`.canary_state` present), rollback forces **0% canary traffic** and stops `api-canary`.
- Blue/green rollback updates `config/caddy/active-upstream.caddy` to the recorded color and reloads Caddy.

## How to test on staging

1. Deploy a new commit:
   ```bash
   ./ops/deploy.sh
   ```
2. Verify health:
   ```bash
   ./ops/rollback.sh --verify-only
   ```
3. Roll back to last known good:
   ```bash
   ./ops/rollback.sh
   ```
4. Verify health again:
   ```bash
   ./ops/rollback.sh --verify-only
   ```
5. Test DB-ahead protection:
   - Deploy a commit with a newer migration.
   - Attempt rollback (should refuse):
     ```bash
     ./ops/rollback.sh
     ```
   - Force rollback with explicit flags (only if you accept the risk):
     ```bash
     ./ops/rollback.sh --allow-db-ahead --i-accept-forward-only-db
     ```
