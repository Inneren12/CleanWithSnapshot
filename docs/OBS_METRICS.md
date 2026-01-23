# Observability Metrics (Prometheus)

This service exposes Prometheus metrics at `/metrics` when `METRICS_ENABLED=true`.
HTTP request metrics are emitted with **low-cardinality labels** to keep SLOs stable:

- `method`
- `route` (FastAPI route templates, e.g. `/v1/bookings/{booking_id}`)
- `status_class` (`2xx`, `4xx`, `5xx`, or `unknown`)
- `service` (defaults to `app_name`)

## Core HTTP Metrics

- `http_requests_total{method,route,status_class,service}`: Request count by route template.
- `http_request_latency_seconds_bucket{method,route,status_class,service}`: Latency histogram buckets.

## PromQL Examples

### Request Rate (All Requests)
```
sum by (service) (rate(http_requests_total[5m]))
```

### Error Rate (5xx)
```
sum by (service) (rate(http_requests_total{status_class="5xx"}[5m]))
  /
clamp_min(sum by (service) (rate(http_requests_total[5m])), 1)
```

### P95 Latency (All Routes)
```
histogram_quantile(
  0.95,
  sum by (le, service) (rate(http_request_latency_seconds_bucket[5m]))
)
```

### P95 Latency (Per Route)
```
histogram_quantile(
  0.95,
  sum by (le, route, service) (rate(http_request_latency_seconds_bucket[5m]))
)
```

### Burn-Rate Alert Example (30d SLO, 99.9% success)
```
# Fast burn (1h window)
(
  sum(rate(http_requests_total{status_class="5xx"}[1h]))
  /
  clamp_min(sum(rate(http_requests_total[1h])), 1)
) > (1 - 0.999) * 14
```

```
# Slow burn (6h window)
(
  sum(rate(http_requests_total{status_class="5xx"}[6h]))
  /
  clamp_min(sum(rate(http_requests_total[6h])), 1)
) > (1 - 0.999) * 6
```

## Notes

- Avoid user/org IDs or raw paths in labels.
- `/metrics` is token-protected in production; use the configured bearer token for scrapes.

## Prometheus Auth Token (Prod + Dev)

Prometheus must present a bearer token when scraping `/metrics` in prod (`APP_ENV=prod`).
The scrape config reads a token from a mounted secret file.

### Create and store the token

1. Generate a token and store it on the host (not in git):

   ```
   sudo install -d /opt/cleaning/secrets
   openssl rand -hex 32 | sudo tee /opt/cleaning/secrets/prom_metrics_token >/dev/null
   sudo chmod 0400 /opt/cleaning/secrets/prom_metrics_token
   ```

2. Configure docker-compose to mount it:

   - Default (dev): `./secrets/prom_metrics_token`
   - Prod: set `PROM_METRICS_TOKEN_FILE=/opt/cleaning/secrets/prom_metrics_token`

   The Prometheus service mounts this file to `/run/secrets/prom_metrics_token`
   and uses `bearer_token_file` in `prometheus.yml`.

### Local/dev setup

If you want Prometheus running locally, either:

- Create an empty token file at `./secrets/prom_metrics_token`, or
- Set `PROM_METRICS_TOKEN_FILE` to a local path containing a token that matches
  your API's metrics auth.

### Ops verification checklist

- Prometheus **/targets** shows `clean-api` **UP** (no 401).
- Run `up{job="clean-api"}` and confirm samples are present.
