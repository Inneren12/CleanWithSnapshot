# Load testing (k6)

This repo includes a lightweight k6 harness under `load-tests/k6/` for smoke load tests against
health, admin, and public booking flows. All configuration is provided via environment variables
so secrets are never committed.

## Requirements

- `k6` installed locally (https://k6.io/docs/get-started/installation/)
- Access to the target environment (staging recommended)

## Environment variables

| Variable | Purpose | Required |
| --- | --- | --- |
| `BASE_URL` | API base URL (e.g. `https://api.example.com`) | ✅ |
| `ADMIN_USER` | Admin basic auth username | admin_list.js only |
| `ADMIN_PASSWORD` | Admin basic auth password | admin_list.js only |
| `ADMIN_AUTH_HEADER` | Full Authorization header override (e.g. `Basic ...` or `Bearer ...`) | optional (admin_list.js) |
| `BOOKING_CAPTCHA_TOKEN` | Captcha token if CAPTCHA_MODE is enabled | booking_flow.js only |

## Scenarios

### Health & readiness

```bash
k6 run load-tests/k6/healthz.js
```

Targets:
- `GET /healthz`
- `GET /readyz`

Thresholds (soft start):
- `http_req_failed` < 1%
- `http_req_duration` p95 < 500ms

### Admin API (2–3 critical endpoints)

```bash
ADMIN_USER=... ADMIN_PASSWORD=... \
  k6 run load-tests/k6/admin_list.js
```

Targets:
- `GET /v1/admin/whoami`
- `GET /v1/admin/profile`
- `GET /v1/admin/jobs/status`

Thresholds (soft start):
- `http_req_failed` < 2%
- `http_req_duration` p95 < 800ms

### Public booking flow

```bash
BASE_URL=... BOOKING_CAPTCHA_TOKEN=... \
  k6 run load-tests/k6/booking_flow.js
```

Flow:
1. `POST /v1/estimate`
2. `POST /v1/leads`
3. `GET /v1/slots`
4. `POST /v1/bookings`

Thresholds (soft start):
- `http_req_failed` < 2%
- `http_req_duration` p95 < 1200ms

## Notes

- Run against staging first to confirm data assumptions and slot availability.
- If captcha is enabled on the environment, provide `BOOKING_CAPTCHA_TOKEN`.
- The booking flow expects slot availability for the requested date; choose a date range
  in staging that returns slots to avoid early exits.
