# Admin entrypoints

These URLs are intended for operators and support staff. All routes require admin authentication (Basic Auth or the configured admin auth flow).

## Primary UI

- `https://<domain>/admin` redirects to the API admin entrypoint (`https://api.<domain>/v1/admin`).
- `https://api.<domain>/v1/admin` redirects to the admin UI landing page (`/v1/admin/ui/invoices`). This is the canonical landing page for operators.

When `NEXT_PUBLIC_SHOW_ADMIN_LINK=true` is set for the web app, the public site header shows an “Admin” link pointing at `/admin`. In docker-compose deployments, set `NEXT_PUBLIC_SHOW_ADMIN_LINK` so the web build arg is available at compile time.

## Common UI pages

- Observability: `https://api.<domain>/v1/admin/observability`
- Invoices: `https://api.<domain>/v1/admin/ui/invoices`
- Dispatch board: `https://api.<domain>/v1/admin/ui/dispatch`
- Workers: `https://api.<domain>/v1/admin/ui/workers`

## Helpful JSON endpoints

- Health: `https://api.<domain>/healthz`
- Readiness: `https://api.<domain>/readyz`
- Admin identity: `https://api.<domain>/v1/admin/whoami`
