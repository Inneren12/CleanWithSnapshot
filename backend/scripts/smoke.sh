#!/usr/bin/env bash
set -euo pipefail

base_url=${1:-${SMOKE_BASE_URL:-}}
admin_user=${ADMIN_BASIC_USERNAME:-}
admin_pass=${ADMIN_BASIC_PASSWORD:-}

if [[ -z "${base_url}" ]]; then
  echo "Usage: $0 <base_url>" >&2
  echo "Alternatively, set SMOKE_BASE_URL" >&2
  exit 1
fi

if [[ -z "${admin_user}" || -z "${admin_pass}" ]]; then
  echo "ADMIN_BASIC_USERNAME and ADMIN_BASIC_PASSWORD must be set for admin smoke checks" >&2
  exit 1
fi

if ! command -v curl >/dev/null 2>&1; then
  echo "curl is required" >&2
  exit 1
fi

if ! command -v jq >/dev/null 2>&1; then
  echo "jq is required" >&2
  exit 1
fi

base_url="${base_url%/}"
whoami_endpoint="${base_url}/v1/admin/whoami"

log() { printf "[smoke] %s\n" "$*"; }

log "Checking admin auth at ${whoami_endpoint}"

status_wrong=$(curl -s -o /dev/null -w "%{http_code}" -u "wrong:creds" "${whoami_endpoint}")
if [[ "${status_wrong}" != "401" ]]; then
  echo "Expected 401 for wrong credentials, got ${status_wrong}" >&2
  exit 1
fi

response=$(curl -fsS -u "${admin_user}:${admin_pass}" "${whoami_endpoint}")
username=$(printf '%s' "${response}" | jq -r '.username')
role=$(printf '%s' "${response}" | jq -r '.role')

if [[ -z "${username}" || "${username}" == "null" ]]; then
  echo "Failed to resolve admin username from whoami response" >&2
  exit 1
fi

log "Authenticated as ${username} (role=${role})"
