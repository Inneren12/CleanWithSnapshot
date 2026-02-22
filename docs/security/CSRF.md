# CSRF Protection

## Scope
CSRF is enforced for all state-changing requests (`POST`, `PUT`, `PATCH`, `DELETE`) that authenticate via cookies:

- `client_session`
- `worker_session`
- `saas_session`

Enforcement is centralized in `CSRFMiddleware` and uses `require_csrf` from `backend/app/infra/csrf.py`.

## Token model
This service uses a double-submit token model:

1. Server issues a `csrf_token` cookie on HTML/UI bootstrap endpoints.
2. Client sends the same token as `X-CSRF-Token` (or form field `csrf_token`) on protected requests.
3. Backend compares the request token with the cookie token and rejects mismatches with `403`.

## Frontend usage
Admin frontend requests should use `resolveAdminRequestHeaders(...)` from `web/app/admin/lib/adminAuth.ts`.
That helper automatically adds `X-CSRF-Token` from the `csrf_token` cookie.

## Safe exemptions
The following endpoints are exempt because they are signature-authenticated webhooks:

- `/v1/payments/stripe/webhook`
- `/stripe/webhook`

## Token-auth exceptions
Requests carrying an `Authorization` header are treated as explicit non-cookie auth flows and are not CSRF-gated by middleware.
Use this only for APIs authenticated with bearer/basic tokens where CSRF is not applicable.

## How to exempt a route safely
Prefer avoiding exemptions. If an exemption is required:

1. Keep it narrow to an exact path.
2. Document the alternate integrity/auth mechanism (e.g., webhook signature).
3. Add the path to `CSRF_EXEMPT_PATHS` in `backend/app/infra/csrf.py`.
4. Add tests proving the endpoint remains secure.
