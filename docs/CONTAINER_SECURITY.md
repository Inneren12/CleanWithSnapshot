# Container filesystem hardening

## Why run as non-root
Running containers as a dedicated non-root user limits the blast radius of a compromised process by preventing privileged filesystem access and reducing the impact of container escapes. The backend and web images both use an `app` user and drop privileges before startup.

## Writable runtime directories (least privilege)

### Backend
The backend uses the local storage backend when `ORDER_STORAGE_BACKEND=local`, writing files under `ORDER_UPLOAD_ROOT` via the local storage backend. The default value is `tmp` (relative to `/app`), and production examples point to `/app/var/uploads/orders`.

To keep write access scoped to the minimum required paths, the backend image explicitly creates and owns only:

- `/app/tmp` (default `ORDER_UPLOAD_ROOT` when it is left as `tmp`).
- `/app/var/uploads` and `/app/var/uploads/orders` (typical `ORDER_UPLOAD_ROOT` target used in production and in `docker-compose` volume mounts).

### Web
The web runtime does not require explicit writable application directories beyond standard system paths (e.g. `/tmp`). The image runs as the `app` user and only relies on the runtime filesystem provided by the base image.

## Local verification (CI-friendly)
Use the following commands to verify non-root execution and runtime directory access without additional dependencies:

### Backend
```sh
# Non-root UID check and required writable directories
docker run --rm cleanwithsnapshot-api:ci sh -lc 'id -u; test "$(id -u)" -ne 0; test -w /app/tmp; test -w /app/var/uploads; test -w /app/var/uploads/orders'
```

### Web
```sh
# Non-root UID check
docker run --rm cleanwithsnapshot-web:ci sh -lc 'id -u; test "$(id -u)" -ne 0'
```

## Rollback
If a rollback is required, revert the container hardening changes by restoring the previous Dockerfiles and rebuild the images.

- Backend: restore the previous ownership commands that recursively changed `/app` ownership.
- Web: restore the previous `COPY` + `chown -R` layering.

Rebuild and redeploy:

```sh
docker compose build api web
docker compose up -d api web
```
