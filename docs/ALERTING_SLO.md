# SLO Alerting (Burn Rate)

This service uses Prometheus multi-window burn-rate alerts to page on sustained
error budget consumption for availability and latency SLOs.

## Alert coverage

- **Availability SLO (99% success, 30d)**
  - Fast burn: 5m + 1h windows (page)
  - Slow burn: 30m + 6h windows (ticket)
- **Latency SLO (p95 < 300ms, key routes)**
  - Fast burn: 5m + 1h windows (page)
  - Slow burn: 30m + 6h windows (ticket)

## Runbooks

- [API down](runbooks/api-down.md)
- [Database down](runbooks/db-down.md)
- [High resource usage](runbooks/high-resource-usage.md)

## Alertmanager routing

Alertmanager is configured to route all burn-rate alerts to a single receiver
named `slo-paging`. Configure one (or both) of the following secrets via env:

- `ALERTMANAGER_SLACK_WEBHOOK_URL` (Slack incoming webhook URL)
- `ALERTMANAGER_WEBHOOK_URL` (generic webhook receiver)

Optional:

- `ALERTMANAGER_SLACK_CHANNEL` (defaults to `#alerts`)

## Validation

```sh
promtool check rules prometheus/rules/slo_alerts.yml
```
