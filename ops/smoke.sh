#!/usr/bin/env bash
set -euo pipefail

API_BASE_URL=${API_BASE_URL:-https://api.panidobro.com}
WEB_BASE_URL=${WEB_BASE_URL:-https://panidobro.com}

report=()

check_endpoint() {
  local name="$1"
  local url="$2"
  local attempts=0
  local max_attempts=5
  local status=""

  while [[ $attempts -lt $max_attempts ]]; do
    attempts=$((attempts + 1))
    status=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$url") || status="000"
    if [[ "$status" =~ ^[23][0-9]{2}$ ]]; then
      echo "[OK] $name ($status)"
      report+=("$name: OK ($status)")
      return 0
    fi
    echo "[wait] $name not ready (status: $status). attempt $attempts/$max_attempts"
    sleep 2
  done

  echo "[FAIL] $name failed after $max_attempts attempts (last status: $status)" >&2
  report+=("$name: FAIL ($status)")
  return 1
}

api_status=0
web_status=0
dlq_status=0

check_endpoint "API /healthz" "$API_BASE_URL/healthz" || api_status=$?
check_endpoint "Web root" "$WEB_BASE_URL/" || web_status=$?

check_dlq_backlog() {
  local admin_user="${ADMIN_BASIC_USERNAME:-}"
  local admin_pass="${ADMIN_BASIC_PASSWORD:-}"

  if [[ -z "$admin_user" || -z "$admin_pass" ]]; then
    echo "[skip] DLQ backlog check (missing admin credentials)"
    report+=("DLQ backlog: SKIP (missing admin creds)")
    return 0
  fi

  local url="${API_BASE_URL%/}/v1/admin/queue/dlq?kind=all&limit=1"
  local response
  if ! response=$(curl -fsS -u "$admin_user:$admin_pass" "$url"); then
    echo "[FAIL] DLQ backlog check failed (unable to query endpoint)" >&2
    report+=("DLQ backlog: FAIL (query_failed)")
    return 1
  fi

  local total outbox export
  read -r total outbox export <<<"$(python - <<'PY' <<<"$response"
import json
import sys

data = json.load(sys.stdin)
total = int(data.get("total", 0) or 0)
outbox = int(data.get("outbox_dead_count", 0) or 0)
export = int(data.get("export_dead_count", 0) or 0)
print(total, outbox, export)
PY
)"

  if [[ "$total" -gt 0 ]]; then
    echo "[FAIL] DLQ backlog detected (total: $total, outbox: $outbox, export: $export)" >&2
    report+=("DLQ backlog: FAIL (total=$total outbox=$outbox export=$export)")
    return 1
  fi

  echo "[OK] DLQ backlog empty"
  report+=("DLQ backlog: OK")
  return 0
}

check_dlq_backlog || dlq_status=$?

printf '\nSmoke summary:\n'
for line in "${report[@]}"; do
  printf -- "- %s\n" "$line"
done

if [[ $api_status -ne 0 || $web_status -ne 0 || $dlq_status -ne 0 ]]; then
  exit 1
fi

exit 0
