#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
cd "$REPO_ROOT"
STATE_DIR="$REPO_ROOT/ops/state"
LAST_GOOD_FILE="$STATE_DIR/last_good.env"
DEPLOY_STATE_FILE="${DEPLOY_STATE_FILE:-/opt/cleaning/.deploy_state.json}"

record_last_good() {
  local sha="$1"
  local mode="$2"
  local timestamp
  timestamp="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

  mkdir -p "$STATE_DIR"
  cat > "$LAST_GOOD_FILE" <<EOF
LAST_GOOD_SHA=$sha
LAST_GOOD_MODE=$mode
LAST_GOOD_COLOR=
LAST_GOOD_TIMESTAMP=$timestamp
EOF
}

get_db_revision() {
  docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "select version_num from alembic_version"' \
    2>/dev/null | tr -d '[:space:]'
}

get_expected_heads() {
  docker compose exec -T api python - <<'PY'
from alembic.config import Config
from alembic.script import ScriptDirectory

cfg = Config("alembic.ini")
script = ScriptDirectory.from_config(cfg)
heads = script.get_heads()
print(" ".join(heads))
PY
}

record_deploy_state() {
  local sha="$1"
  local mode="$2"
  local color="${3:-}"
  local timestamp="$4"
  local db_revision="$5"
  local expected_heads="$6"

  mkdir -p "$(dirname "$DEPLOY_STATE_FILE")"
  python3 - <<PY
import json
from pathlib import Path

data = {
    "last_good_sha": "${sha}",
    "last_good_timestamp": "${timestamp}",
    "deploy_mode": "${mode}",
    "deploy_color": "${color}",
    "db_revision": "${db_revision}",
    "expected_heads": "${expected_heads}".split() if "${expected_heads}" else [],
}

Path("${DEPLOY_STATE_FILE}").write_text(json.dumps(data, indent=2) + "\n")
PY
}

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
  -e "caddy_config/" \
  -e "ops/state/last_good.env" \
  -e ".deploy_state.json"

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

deploy_timestamp="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
db_revision="$(get_db_revision)"
expected_heads="$(get_expected_heads)"
record_deploy_state "$updated_sha" "standard" "" "$deploy_timestamp" "$db_revision" "$expected_heads"

record_last_good "$updated_sha" "standard"
echo "Recorded last known good deploy: $updated_sha"
echo "Recorded deploy state: $DEPLOY_STATE_FILE"

echo "Deploy completed successfully."
