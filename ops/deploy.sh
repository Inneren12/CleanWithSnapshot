#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
cd "$REPO_ROOT"

echo "== CleanWithSnapshot deploy =="

echo "Repo root: $REPO_ROOT"
current_sha="$(git rev-parse HEAD)"
echo "Current revision: $current_sha"

if ! git config remote.origin.url >/dev/null; then
  echo "ERROR: remote 'origin' is not configured. Configure it before deploying." >&2
  exit 1
fi

echo "Fetching latest origin/main..."
git fetch origin

echo "Resetting working tree to origin/main (preserving runtime artifacts)..."
git reset --hard origin/main

git clean -xfd \
  -e ".env" \
  -e "logs/" \
  -e "var/" \
  -e "tmp/" \
  -e "pg_data/" \
  -e "caddy_data/" \
  -e "caddy_config/"

updated_sha="$(git rev-parse HEAD)"
echo "Updated revision: $updated_sha"

if [[ ! -f .env ]]; then
  echo "WARNING: .env not found in repo root. Ensure environment variables are present before continuing." >&2
fi

echo "Building images..."
docker compose build

echo "Starting services..."
docker compose up -d --remove-orphans

echo "Waiting for database to become ready..."
for attempt in $(seq 1 30); do
  if docker compose exec -T db sh -c 'pg_isready -U "${POSTGRES_USER}" -d "${POSTGRES_DB}"' >/dev/null 2>&1; then
    echo "Database is ready."
    break
  fi
  if [[ "$attempt" -eq 30 ]]; then
    echo "ERROR: database did not become ready in time." >&2
    exit 1
  fi
  sleep 2
done

echo "Running migrations..."
docker compose exec -T api alembic upgrade head

echo "Migrations completed. No API restart required beyond compose up."

echo "Running smoke tests..."
"$REPO_ROOT/ops/smoke.sh"

echo "Deploy completed successfully."
