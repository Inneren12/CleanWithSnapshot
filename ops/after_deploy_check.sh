#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="/etc/cleaning/cleaning.env"
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
ROOT_DIR=$(cd "${SCRIPT_DIR}/.." && pwd)

if [[ ! -f "$ENV_FILE" ]]; then
  echo "[error] missing env file: $ENV_FILE" >&2
  exit 1
fi

set -a
source "$ENV_FILE"
set +a

API_BASE_URL=${API_BASE_URL:-https://api.panidobro.com}
WEB_BASE_URL=${WEB_BASE_URL:-https://panidobro.com}

cd "$ROOT_DIR"

echo "== env audit =="
python3 ops/env_audit.py --env "$ENV_FILE"

echo "== docker compose ps =="
docker compose ps

echo "== api healthz =="
curl -fsS "$API_BASE_URL/healthz"

echo "== api readyz =="
readyz_json=$(curl -fsS "$API_BASE_URL/readyz")
printf '%s\n' "$readyz_json"

printf '%s\n' "$readyz_json" | python3 - <<'PY'
import json
import sys

data = json.load(sys.stdin)
jobs = next((check for check in data.get("checks", []) if check.get("name") == "jobs"), None)
if not jobs:
    print("readyz jobs check missing", file=sys.stderr)
    sys.exit(1)

detail = jobs.get("detail", {})
summary = {
    "ok": jobs.get("ok"),
    "enabled": detail.get("enabled"),
    "age_seconds": detail.get("age_seconds"),
    "runner_id": detail.get("runner_id"),
}
print("Jobs heartbeat summary:", json.dumps(summary, sort_keys=True))
PY

echo "== web head =="
curl -sSI "$WEB_BASE_URL/" | head -n 5

echo "== admin whoami =="
if [[ -z "${ADMIN_BASIC_USERNAME:-}" || -z "${ADMIN_BASIC_PASSWORD:-}" ]]; then
  echo "[error] ADMIN_BASIC_USERNAME and ADMIN_BASIC_PASSWORD must be set" >&2
  exit 1
fi
curl -fsS -u "${ADMIN_BASIC_USERNAME}:${ADMIN_BASIC_PASSWORD}" "$API_BASE_URL/v1/admin/whoami"

printf '\n== uploads writable ==\n'
docker compose exec -T api sh -lc 'test -n "$ORDER_UPLOAD_ROOT" && touch "$ORDER_UPLOAD_ROOT/.write_test" && rm "$ORDER_UPLOAD_ROOT/.write_test"'

echo "== smoke =="
API_BASE_URL="$API_BASE_URL" WEB_BASE_URL="$WEB_BASE_URL" ./ops/smoke.sh
