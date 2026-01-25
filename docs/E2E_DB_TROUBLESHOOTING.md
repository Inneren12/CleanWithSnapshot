# E2E DB Troubleshooting

This guide covers common causes of E2E database startup failures and how to diagnose them.

## Common causes

- **Mismatched DB env vars**: Ensure `POSTGRES_DB`, `POSTGRES_USER`, and `POSTGRES_PASSWORD` match between the
  workflow, `docker-compose.yml`, and `docker-compose.e2e.yml`.
- **Stale volumes**: A reused volume can keep old users or databases. Run a full teardown with
  `docker compose ... down -v` before retrying.
- **Migration failures**: The API runs `alembic upgrade head` on boot in E2E. Failed migrations can prevent the API
  from starting, which then causes the stack to fail health checks.
- **Extension preload issues**: Missing `shared_preload_libraries=pg_stat_statements` can cause extension checks to fail
  depending on the migration path.

## How to reproduce locally

```bash
# Clean slate
POSTGRES_DB=cleaning POSTGRES_USER=postgres POSTGRES_PASSWORD=postgres \
  docker compose -f docker-compose.yml -f docker-compose.e2e.yml down -v

# Start services
POSTGRES_DB=cleaning POSTGRES_USER=postgres POSTGRES_PASSWORD=postgres \
  docker compose -f docker-compose.yml -f docker-compose.e2e.yml up -d db redis api web jobs

# Check DB health
POSTGRES_DB=cleaning POSTGRES_USER=postgres POSTGRES_PASSWORD=postgres \
  docker compose -f docker-compose.yml -f docker-compose.e2e.yml exec -T db \
  psql -U postgres -d cleaning -c "select 1;"
```

## Logs to check

```bash
# Container status
docker compose -f docker-compose.yml -f docker-compose.e2e.yml ps

# DB logs
docker compose -f docker-compose.yml -f docker-compose.e2e.yml logs --no-color db --tail=300

# API logs (migrations run here)
docker compose -f docker-compose.yml -f docker-compose.e2e.yml logs --no-color api --tail=300

# DB health inspection
DB_ID=$(docker compose -f docker-compose.yml -f docker-compose.e2e.yml ps -q db)
docker inspect "$DB_ID" --format '{{json .State.Health}}'
```

## SQL readiness check
If the DB is marked healthy but the app still cannot connect, validate with a direct SQL call:

```bash
docker compose -f docker-compose.yml -f docker-compose.e2e.yml exec -T db \
  psql -U postgres -d cleaning -c "select 1;"
```
