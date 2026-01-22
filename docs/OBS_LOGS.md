# Log aggregation with Grafana + Loki + Promtail

## Start the stack

Run the main services plus the observability override:

```bash
docker compose -f docker-compose.yml -f docker-compose.observability.yml up -d --wait
```

## Access Grafana locally

Grafana is bound to `127.0.0.1:3001`:

- URL: `http://127.0.0.1:3001`
- Username: `admin`
- Password: `${GRAFANA_ADMIN_PASSWORD:-admin}` (or whatever you set in your environment)

## Query logs by request_id or org_id (JSON fields)

Promtail forwards logs with low-cardinality labels (`service`, `env`, `container`). Use LogQL JSON parsing to query structured fields without turning them into labels:

```logql
{service="api"} | json | request_id="<request-id>"
```

```logql
{service="web"} | json | org_id="<org-id>"
```

You can also scope to background workers:

```logql
{service="jobs"} | json
```

## Environment label

Promtail adds the `env` label from `APP_ENV` (defaults to `local`). Set it before starting the stack if you want a different value:

```bash
APP_ENV=staging docker compose -f docker-compose.yml -f docker-compose.observability.yml up -d --wait
```
