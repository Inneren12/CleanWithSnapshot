#!/usr/bin/env bash
set -euo pipefail

cd /opt/cleaning/backend
git pull

cd /opt/cleaning
docker compose up -d --build

echo "Waiting for healthz..."
for i in {1..40}; do
  if curl -fsS https://api.panidobro.com/healthz >/dev/null 2>&1; then
    echo "DEPLOY OK"
    exit 0
  fi
  sleep 2
done

echo "DEPLOY FAILED: healthz still not OK"
docker compose logs --tail=200 api || true
docker compose logs --tail=200 caddy || true
exit 1
