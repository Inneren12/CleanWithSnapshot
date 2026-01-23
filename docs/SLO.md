# Service Level Objectives (SLOs)

These SLOs apply to the public API and are measured using Prometheus metrics
emitted from the `/metrics` endpoint when `METRICS_ENABLED=true`.

## SLOs

### Availability SLO
- **Target:** 99.0% successful requests over a rolling 30-day window.
- **SLI:** Request success rate based on `http_requests_total`.
- **Definition:**
  - Success = HTTP status class `2xx` or `3xx`.
  - Total = all HTTP requests (including `4xx` and `5xx`).
  - Metric: `sli:request_success_rate30d`.

### Latency SLO
- **Target:** p95 < 300 ms for key routes, evaluated over a rolling 30-day window.
- **SLI:** p95 latency from `http_request_latency_seconds` histogram recorded every 5 minutes.
- **Key routes:**
  - `/v1/bookings`
  - `/v1/customers`
  - `/v1/quotes`
  - `/v1/cleaners`
- **Definition:**
  - p95 latency computed from `http_request_latency_seconds_bucket`.
  - Metric: `sli:latency_p95_5m` (filter by `route` label for key routes; use a 30-day range in dashboards to assess compliance).

### Error-rate SLO
- **Target:** 5xx error rate < 1.0% over a rolling 30-day window.
- **SLI:** 5xx errors divided by total requests.
- **Definition:**
  - Error = HTTP status class `5xx`.
  - Metric: `sli:error_rate30d`.

## Exclusions

- **Planned maintenance windows:** Scheduled downtime is excluded from SLO
  calculations when maintenance is communicated ahead of time.
- **Client-caused errors:** 4xx responses are tracked but do not count as
  server errors in the error-rate SLO.
- **Synthetic traffic:** Load tests and scripted chaos experiments should be
  excluded (filter via Prometheus labels or separate scrape targets).

## Notes

- SLOs assume `METRICS_ENABLED=true` and Prometheus scraping `/metrics`.
- Adjust the route list if the API surface changes; the `route` label in the
  metrics should match the canonical route names.
