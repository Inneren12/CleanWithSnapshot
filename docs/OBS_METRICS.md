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
