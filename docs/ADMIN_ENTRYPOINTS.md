# Admin entrypoints

These URLs are intended for operators and support staff. All routes require admin authentication (Basic Auth or the configured admin auth flow).

## Primary UI

- `https://api.<domain>/v1/admin` redirects to the admin UI landing page (`/v1/admin/observability`).

## Common UI pages

- Observability (landing): `https://api.<domain>/v1/admin/observability`
- Invoices: `https://api.<domain>/v1/admin/ui/invoices`
- Dispatch board: `https://api.<domain>/v1/admin/ui/dispatch`
- Workers: `https://api.<domain>/v1/admin/ui/workers`

## Helpful JSON endpoints

- Health: `https://api.<domain>/healthz`
- Readiness: `https://api.<domain>/readyz`
- Admin identity: `https://api.<domain>/v1/admin/whoami`
