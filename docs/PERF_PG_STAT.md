# pg_stat_statements enablement

## Overview

This project enables the `pg_stat_statements` extension to capture query-level performance
statistics. The Docker compose configuration preloads the shared library so Postgres exposes
the view on startup, and Alembic manages the extension creation.

## What changed

- Postgres is started with `shared_preload_libraries=pg_stat_statements` and
  `pg_stat_statements.track=all` in `docker-compose.yml`.
- Alembic migration `0088_enable_pg_stat_statements` creates the extension if needed.

## Apply the migration

```bash
docker compose run --rm api alembic upgrade head
```

## Verify

```bash
docker compose exec db psql -U postgres -c "SELECT 1"
docker compose exec db psql -U postgres -c "SELECT * FROM pg_stat_statements LIMIT 1;"
```

## Notes

- `pg_stat_statements` requires the preload setting; if you change database configuration,
  ensure the preload line remains present before relying on the view.
