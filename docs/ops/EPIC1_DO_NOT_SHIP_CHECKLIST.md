# Epic 1 — DO NOT SHIP Checklist

This checklist must pass before shipping any release that includes Epic 1
security controls (upload size cap, CSRF protection, trusted-proxy IP
resolution, Stripe transaction boundaries).

---

## One-Command Local Verify

Run all four Epic 1 smoke tests from the repository root:

```bash
pytest -m epic1 -v
```

Or by name-match (no marker needed):

```bash
pytest -k epic1 -v
```

Expected output — all four tests green:

```
backend/tests/security/test_epic1_smoke.py::test_epic1_upload_size_cap_returns_413        PASSED
backend/tests/security/test_epic1_smoke.py::test_epic1_csrf_blocks_post_without_token     PASSED
backend/tests/security/test_epic1_smoke.py::test_epic1_spoofed_xff_from_untrusted_source_is_ignored  PASSED
backend/tests/security/test_epic1_smoke.py::test_epic1_stripe_called_outside_db_transaction PASSED
```

---

## What Each Test Verifies

| Test | PR | Control |
|---|---|---|
| `test_epic1_upload_size_cap_returns_413` | PR-01 | Upload body exceeding `ORDER_PHOTO_MAX_BYTES` returns **HTTP 413** without buffering the payload into server memory |
| `test_epic1_csrf_blocks_post_without_token` | PR-04 | A state-changing request to a CSRF-protected endpoint without a valid token returns **HTTP 403** |
| `test_epic1_spoofed_xff_from_untrusted_source_is_ignored` | PR-03 | A spoofed `X-Forwarded-For` header from an address not in `TRUSTED_PROXY_CIDRS` is ignored; the resolved client IP equals the TCP connection host |
| `test_epic1_stripe_called_outside_db_transaction` | PR-02 | `create_checkout_session` is called in Phase 1 (before `session.begin()`), never inside a DB transaction |

---

## CI Verify

The `epic1` tests run as part of the standard unit-test job (no special
configuration needed):

```yaml
# .github/workflows/ci.yml — example step
- name: Run Epic 1 verification
  run: pytest -m epic1 -v --tb=short
```

Because all tests use an in-memory SQLite database and mock Stripe, they
require no external services and run fast in CI.

If you want to run only the Epic 1 smoke tests in isolation (e.g., as a
fast gate before a deploy):

```bash
pytest backend/tests/security/test_epic1_smoke.py -v
```

---

## Required Config Environment Variables

The following environment variables **must** be set correctly in production
for the Epic 1 controls to be effective. Missing or wrong values are a
**DO NOT SHIP** blocker.

### PR-03 — Trusted Proxy CIDR

| Variable | Required | Description |
|---|---|---|
| `TRUSTED_PROXY_CIDRS` | Yes (for proxy deployments) | Comma-separated CIDRs of trusted reverse-proxy addresses (e.g. Caddy container subnet). Set to the **narrowest** range that covers your ingress only. **Never** set to `0.0.0.0/0`. |

Verification:

```bash
# Confirm the value in the running container
docker compose exec api printenv TRUSTED_PROXY_CIDRS
```

Expected: a private CIDR such as `172.18.0.0/16` — never a public range.

See [docs/security/TRUSTED_PROXY_IP.md](../security/TRUSTED_PROXY_IP.md) for
full configuration guidance.

### PR-01 — Upload Size Cap

| Variable | Default | Description |
|---|---|---|
| `ORDER_PHOTO_MAX_BYTES` | `10485760` (10 MiB) | Maximum allowed upload size in bytes. Set per your storage budget and DoS risk tolerance. |

Verification:

```bash
docker compose exec api printenv ORDER_PHOTO_MAX_BYTES
```

Expected: a value ≤ 10485760 (10 MiB) for standard deployments.

See [docs/security/UPLOADS.md](../security/UPLOADS.md) for full details.

---

## Logs to Check

After deploying, confirm the following structured-log events appear under
normal operation (no errors, no unexpected warnings).

### PR-03 — Proxy trust

Look for **absence** of this warning (means no misconfigured CIDRs):

```json
{ "event": "invalid_trusted_proxy_cidr", "cidr": "..." }
```

If this appears, a CIDR in `TRUSTED_PROXY_CIDRS` is malformed. Fix it
immediately — invalid CIDRs are silently skipped (fail-closed), which may
mean your real-client-IP resolution is degraded.

### PR-02 — Stripe boundary

On a successful booking with deposit, confirm the structured log shows Stripe
success **before** the booking row is committed. Look for ordering:

1. `stripe_checkout_creation_started` (or equivalent) — Phase 1
2. `booking_created` — Phase 2

If compensation fires (DB failure after Stripe success), you should see:

```json
{ "event": "stripe_compensation_triggered", "booking_id": "...", "stripe_session_id": "cs_..." }
```

See [docs/payments/TRANSACTION_BOUNDARIES.md](../payments/TRANSACTION_BOUNDARIES.md)
for the full two-phase pattern.

### PR-04 — CSRF

A 403 from CSRF enforcement logs:

```
CSRF token missing
```
or
```
CSRF token invalid or missing
```

A spike in 403s on admin UI endpoints after a deploy is a signal that the
CSRF cookie is not being issued or forwarded correctly. Check:

- Admin UI is served over HTTPS in production (cookie `Secure` flag).
- Caddy is not stripping the `csrf_token` cookie.

---

## Related Docs

- [docs/security/UPLOADS.md](../security/UPLOADS.md) — PR-01 upload streaming details
- [docs/payments/TRANSACTION_BOUNDARIES.md](../payments/TRANSACTION_BOUNDARIES.md) — PR-02 Stripe boundary rule
- [docs/security/TRUSTED_PROXY_IP.md](../security/TRUSTED_PROXY_IP.md) — PR-03 trusted proxy configuration
- [docs/security/CSRF.md](../security/CSRF.md) — PR-04 CSRF token model
