# SLO PromQL Queries

Use these PromQL snippets in Prometheus or Grafana to validate SLOs and SLIs.

## Availability (success rate)

- **5m success rate (recording rule):**
  ```promql
  sli:request_success_rate5m
  ```

- **30d success rate (recording rule):**
  ```promql
  sli:request_success_rate30d
  ```

- **Success rate by service (raw query):**
  ```promql
  sum(rate(http_requests_total{status_class=~"2xx|3xx"}[5m])) by (service)
    /
  clamp_min(sum(rate(http_requests_total[5m])) by (service), 1)
  ```

## Error rate

- **5m error rate (recording rule):**
  ```promql
  sli:error_rate5m
  ```

- **30d error rate (recording rule):**
  ```promql
  sli:error_rate30d
  ```

- **5xx error rate by service (raw query):**
  ```promql
  sum(rate(http_requests_total{status_class="5xx"}[5m])) by (service)
    /
  clamp_min(sum(rate(http_requests_total[5m])) by (service), 1)
  ```

## Latency (p95)

- **p95 latency (recording rule):**
  ```promql
  sli:latency_p95_5m
  ```

- **p95 latency by key route (raw query):**
  ```promql
  histogram_quantile(
    0.95,
    sum(rate(http_request_latency_seconds_bucket{route=~"/v1/(bookings|customers|quotes|cleaners)"}[5m]))
      by (le, route)
  )
  ```

## Request volume

- **Requests per second (raw query):**
  ```promql
  sum(rate(http_requests_total[5m]))
  ```
