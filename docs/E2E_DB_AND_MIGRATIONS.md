# E2E DB & Migration Readiness

This guide explains how the E2E stack validates Postgres readiness and how migration failures are surfaced.

## Why pg_stat_statements must be preloaded
The Alembic migration `0088_enable_pg_stat_statements` creates the extension. Postgres only exposes the extension
when `shared_preload_libraries` includes `pg_stat_statements`, so the E2E DB container preloads it via
`docker-compose.e2e.yml`. If the preload is missing, the migration fails with a clear error message.

## E2E env file validation
The workflow generates `backend/.env.e2e.ci` from `backend/.env.example` and enforces required keys derived from
`backend/app/settings.py`. The preflight step fails before containers start if the file is missing, empty, or lacks
required keys. Only key names are printed to avoid leaking secrets.

## E2E startup sequence (CI)
1. Start DB + Redis.
2. Wait for DB healthcheck (pg_isready) and validate `shared_preload_libraries`.
3. Run a SQL readiness probe: `select 1;`.
4. Start API/Web/Jobs, then wait for HTTP readiness.

## Debugging migration failures
If API startup fails, the workflow prints:
- API logs (tail)
- DB logs (tail)
- Alembic `current` and `heads`

You can reproduce locally:

```bash
POSTGRES_DB=cleaning POSTGRES_USER=postgres POSTGRES_PASSWORD=postgres \
  docker compose -f docker-compose.yml -f docker-compose.e2e.yml down -v

POSTGRES_DB=cleaning POSTGRES_USER=postgres POSTGRES_PASSWORD=postgres \
  docker compose -f docker-compose.yml -f docker-compose.e2e.yml up -d db redis

POSTGRES_DB=cleaning POSTGRES_USER=postgres POSTGRES_PASSWORD=postgres \
  docker compose -f docker-compose.yml -f docker-compose.e2e.yml exec -T db \
  psql -U postgres -d cleaning -c "SHOW shared_preload_libraries;"

POSTGRES_DB=cleaning POSTGRES_USER=postgres POSTGRES_PASSWORD=postgres \
  docker compose -f docker-compose.yml -f docker-compose.e2e.yml up -d api web jobs
```
