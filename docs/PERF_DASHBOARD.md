# Grafana performance dashboard (pg_stat_statements)

This dashboard surfaces the most expensive Postgres queries by total time, mean time, and call count using `pg_stat_statements`.

## Prerequisites

- `pg_stat_statements` is enabled. See [PERF_PG_STAT.md](./PERF_PG_STAT.md).
- A read-only Postgres user exists for Grafana.

Example SQL to create a read-only user:

```sql
CREATE ROLE grafana_ro WITH LOGIN PASSWORD 'replace-me';
GRANT CONNECT ON DATABASE cleaning TO grafana_ro;
GRANT USAGE ON SCHEMA public TO grafana_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO grafana_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO grafana_ro;
```

## Configuration

Set the following environment variables (used by Grafana provisioning):

```bash
export POSTGRES_HOST=db
export POSTGRES_DB=cleaning
export POSTGRES_READONLY_USER=grafana_ro
export POSTGRES_READONLY_PASSWORD=replace-me
```

Start Grafana with the observability stack:

```bash
docker compose -f docker-compose.yml -f docker-compose.observability.yml up -d grafana
```

## Dashboard

The dashboard is provisioned at **Observability → Postgres Query Performance** and includes:

- Top queries by `total_time`
- Top queries by `mean_time`
- Top queries by `calls`
