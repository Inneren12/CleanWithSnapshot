#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
cd "$REPO_ROOT"

STATE_DIR="$REPO_ROOT/ops/state"
LAST_GOOD_FILE="$STATE_DIR/last_good.env"
DEPLOY_STATE_FILE="${DEPLOY_STATE_FILE:-/opt/cleaning/.deploy_state.json}"
ROLLBACK_LOG_FILE="$STATE_DIR/rollback.log"
CANARY_STATE_FILE="$REPO_ROOT/.canary_state"

COMPOSE_STANDARD=(docker compose)
COMPOSE_BLUE_GREEN=(docker compose -f docker-compose.yml -f docker-compose.blue-green.yml)
COMPOSE_CANARY=(docker compose -f docker-compose.yml -f docker-compose.canary.yml)

API_BASE_URL=${API_BASE_URL:-https://api.panidobro.com}
WEB_BASE_URL=${WEB_BASE_URL:-https://panidobro.com}

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

DRY_RUN=false
VERIFY_ONLY=false
ALLOW_DB_AHEAD=false
ACCEPT_FORWARD_ONLY_DB=false
TARGET_SHA=""
TARGET_TAG=""

log_info() {
  echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
  echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warn() {
  echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
  echo -e "${RED}[ERROR]${NC} $1" >&2
}

on_error() {
  if [[ "$DRY_RUN" == "true" ]]; then
    return
  fi
  log_error "Rollback failed. Collecting diagnostics..."
  diagnostics
}

usage() {
  cat <<'EOF'
Usage:
  ./ops/rollback.sh [options]

Options:
  --sha <sha>                    Roll back to a specific git SHA.
  --tag <tag>                    Roll back to a specific git tag.
  --dry-run                      Print commands without making changes.
  --verify-only                  Only verify current health/version, no changes.
  --allow-db-ahead               Allow rollback when DB is ahead of target code.
  --i-accept-forward-only-db     Required with --allow-db-ahead to confirm risk.
  -h, --help                     Show this help message.
EOF
}

trap on_error ERR

run_cmd() {
  if [[ "$DRY_RUN" == "true" ]]; then
    printf '[dry-run]'
    printf ' %q' "$@"
    printf '\n'
    return 0
  fi
  "$@"
}

load_deploy_state() {
  if [[ ! -f "$DEPLOY_STATE_FILE" ]]; then
    log_error "Deploy state file not found: $DEPLOY_STATE_FILE"
    log_error "Run ./ops/deploy.sh first to record a last known good release."
    exit 1
  fi

  eval "$(python3 - <<PY
import json
import shlex
from pathlib import Path

data = json.loads(Path("${DEPLOY_STATE_FILE}").read_text())

def emit(key, value):
    print(f"{key}={shlex.quote(value)}")

emit("STATE_SHA", str(data.get("last_good_sha", "")))
emit("STATE_TIMESTAMP", str(data.get("last_good_timestamp", "")))
emit("STATE_MODE", str(data.get("deploy_mode", "standard")))
emit("STATE_COLOR", str(data.get("deploy_color", "")))
emit("STATE_DB_REVISION", str(data.get("db_revision", "")))
emit("STATE_EXPECTED_HEADS", " ".join(data.get("expected_heads") or []))
PY
)"

  if [[ -z "${STATE_SHA:-}" ]]; then
    log_error "last_good_sha missing in $DEPLOY_STATE_FILE"
    exit 1
  fi
}

resolve_target_sha() {
  if [[ -n "$TARGET_SHA" ]]; then
    echo "$TARGET_SHA"
    return
  fi

  if [[ -n "$TARGET_TAG" ]]; then
    git rev-parse "$TARGET_TAG"
    return
  fi

  load_deploy_state
  echo "$STATE_SHA"
}

resolve_target_mode() {
  if [[ -n "${STATE_MODE:-}" ]]; then
    echo "$STATE_MODE"
  else
    echo "standard"
  fi
}

resolve_target_color() {
  if [[ -n "${STATE_COLOR:-}" ]]; then
    echo "$STATE_COLOR"
  else
    echo ""
  fi
}

record_rollback_event() {
  local from_sha="$1"
  local to_sha="$2"
  local mode="$3"
  local timestamp
  timestamp="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

  mkdir -p "$STATE_DIR"
  printf '%s from=%s to=%s mode=%s\n' "$timestamp" "$from_sha" "$to_sha" "$mode" >> "$ROLLBACK_LOG_FILE"
}

reset_repo_to_sha() {
  local sha="$1"

  run_cmd git fetch origin
  run_cmd git reset --hard "$sha"
  run_cmd git clean -xfd \
    -e ".env" \
    -e "logs/" \
    -e "var/" \
    -e "tmp/" \
    -e "pg_data/" \
    -e "caddy_data/" \
    -e "caddy_config/" \
    -e "ops/state/last_good.env" \
    -e ".deploy_state.json" \
    -e ".canary_state"
}

ensure_canary_stable() {
  if [[ ! -f "$CANARY_STATE_FILE" ]]; then
    return 0
  fi

  log_warn "Canary state detected. Forcing traffic back to stable (0% canary)."
  run_cmd "$REPO_ROOT/ops/generate_canary_caddyfile.sh" 0
  run_cmd "${COMPOSE_STANDARD[@]}" exec -T caddy caddy reload --config /etc/caddy/Caddyfile
  run_cmd "${COMPOSE_CANARY[@]}" stop api-canary || true
  run_cmd "${COMPOSE_STANDARD[@]}" up -d --remove-orphans
  run_cmd rm -f "$CANARY_STATE_FILE"
}

fetch_expected_heads() {
  local service="$1"
  shift
  local -a compose_cmd=("$@")
  if [[ "$DRY_RUN" == "true" ]]; then
    run_cmd "${compose_cmd[@]}" run --rm --no-deps "$service" python - <<'PY' >&2
from alembic.config import Config
from alembic.script import ScriptDirectory

cfg = Config("alembic.ini")
script = ScriptDirectory.from_config(cfg)
heads = script.get_heads()
print(" ".join(heads))
PY
    return 0
  fi
  "${compose_cmd[@]}" run --rm --no-deps "$service" python - <<'PY'
from alembic.config import Config
from alembic.script import ScriptDirectory

cfg = Config("alembic.ini")
script = ScriptDirectory.from_config(cfg)
heads = script.get_heads()
print(" ".join(heads))
PY
}

fetch_db_revision() {
  local -a compose_cmd=("$@")
  if [[ "$DRY_RUN" == "true" ]]; then
    run_cmd "${compose_cmd[@]}" exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "select version_num from alembic_version"' >&2
    return 0
  fi
  "${compose_cmd[@]}" exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "select version_num from alembic_version"' \
    | tr -d '[:space:]'
}

check_migration_compatibility() {
  local expected_heads="$1"
  local current_revision="$2"

  if [[ "$DRY_RUN" == "true" ]]; then
    log_info "Dry-run: skipping migration compatibility check."
    return 0
  fi

  if [[ -z "$expected_heads" ]]; then
    log_warn "Expected migration heads are empty; unable to verify migration compatibility."
    return 0
  fi

  if [[ -z "$current_revision" ]]; then
    log_warn "Current DB revision unavailable; unable to verify migration compatibility."
    return 0
  fi

  if [[ " $expected_heads " == *" $current_revision "* ]]; then
    log_success "DB migration head matches target code: $current_revision"
    return 0
  fi

  log_warn "DB revision ($current_revision) does not match target code heads ($expected_heads)."
  log_warn "Rollback will NOT downgrade the schema (forward-only policy)."

  if [[ "$ALLOW_DB_AHEAD" != "true" || "$ACCEPT_FORWARD_ONLY_DB" != "true" ]]; then
    log_error "Refusing rollback. Pass --allow-db-ahead and --i-accept-forward-only-db to proceed."
    exit 1
  fi

  log_warn "Proceeding despite DB ahead warning (operator accepted forward-only DB risk)."
}

verify_readyz() {
  local readyz_json
  readyz_json=$(curl -fsS "$API_BASE_URL/readyz")
  printf '%s\n' "$readyz_json" | python3 - <<'PY'
import json
import sys

payload = json.load(sys.stdin)
if not payload.get("ok"):
    raise SystemExit("readyz overall status is not ok")

checks = {check["name"]: check for check in payload.get("checks", [])}
migrations = checks.get("migrations", {})
detail = migrations.get("detail", {})
if not migrations.get("ok"):
    raise SystemExit("readyz migrations check failed")
if not detail.get("migrations_current"):
    raise SystemExit("readyz migrations_current is false")
PY
}

verify_health() {
  if [[ "$DRY_RUN" == "true" ]]; then
    log_info "Dry-run: skipping health verification."
    return 0
  fi
  log_info "Verifying /healthz..."
  curl -fsS "$API_BASE_URL/healthz" >/dev/null
  log_success "/healthz OK"

  log_info "Verifying /readyz..."
  verify_readyz
  log_success "/readyz OK (migrations_current)"

  log_info "Running smoke tests..."
  API_BASE_URL="$API_BASE_URL" WEB_BASE_URL="$WEB_BASE_URL" "$REPO_ROOT/ops/smoke.sh"
}

verify_caddy_routes() {
  if [[ "$DRY_RUN" == "true" ]]; then
    log_info "Dry-run: skipping Caddy routing verification."
    return 0
  fi
  log_info "Verifying Caddy routing..."
  curl -fsS "$WEB_BASE_URL/" >/dev/null
  curl -fsS "$API_BASE_URL/healthz" >/dev/null
  log_success "Caddy routing OK"
}

diagnostics() {
  log_warn "Collecting diagnostics..."
  "${COMPOSE_STANDARD[@]}" ps || true
  "${COMPOSE_STANDARD[@]}" logs --tail=200 api web caddy || true
}

rollback_standard() {
  local target_sha="$1"
  local expected_heads="$2"
  local current_revision="$3"

  log_info "Rebuilding images..."
  run_cmd "${COMPOSE_STANDARD[@]}" build

  check_migration_compatibility "$expected_heads" "$current_revision"

  log_info "Recreating services..."
  run_cmd "${COMPOSE_STANDARD[@]}" up -d --remove-orphans

  reload_caddy "${COMPOSE_STANDARD[@]}"

  ensure_canary_stable

  verify_health
  verify_caddy_routes
}

update_caddy_upstream() {
  local color="$1"
  local upstream_file="$REPO_ROOT/config/caddy/upstream-${color}.caddy"
  local active_file="$REPO_ROOT/config/caddy/active-upstream.caddy"

  if [[ ! -f "$upstream_file" ]]; then
    log_error "Upstream config not found: $upstream_file"
    exit 1
  fi

  {
    echo "# Active upstream configuration"
    echo "# This file is managed by ops/rollback.sh"
    echo "# DO NOT EDIT MANUALLY - changes will be overwritten during rollback"
    echo "#"
    echo "# Current active color: $color"
    echo "# Updated: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo ""
    tail -n +5 "$upstream_file"
  } > "$active_file"
}

reload_caddy() {
  local -a compose_cmd=("$@")
  run_cmd "${compose_cmd[@]}" exec -T caddy caddy reload --config /etc/caddy/Caddyfile || \
    run_cmd "${compose_cmd[@]}" restart caddy
}

rollback_blue_green() {
  local target_sha="$1"
  local color="$2"
  local expected_heads="$3"
  local current_revision="$4"

  if [[ -z "$color" ]]; then
    log_error "Missing blue/green color for rollback."
    exit 1
  fi

  log_info "Rebuilding images for $color stack..."
  run_cmd "${COMPOSE_BLUE_GREEN[@]}" build "api-${color}" "web-${color}"

  check_migration_compatibility "$expected_heads" "$current_revision"

  log_info "Starting $color stack services..."
  run_cmd "${COMPOSE_BLUE_GREEN[@]}" up -d "api-${color}" "web-${color}" caddy

  update_caddy_upstream "$color"
  reload_caddy "${COMPOSE_BLUE_GREEN[@]}"

  ensure_canary_stable

  verify_health
  verify_caddy_routes
}

verify_only() {
  log_info "Verify-only mode: no changes will be made."
  log_info "Current git SHA: $(git rev-parse HEAD)"
  verify_health
  verify_caddy_routes
  log_success "Verification complete."
}

main() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --sha)
        TARGET_SHA="${2:-}"
        shift 2
        ;;
      --tag)
        TARGET_TAG="${2:-}"
        shift 2
        ;;
      --dry-run)
        DRY_RUN=true
        shift
        ;;
      --verify-only)
        VERIFY_ONLY=true
        shift
        ;;
      --allow-db-ahead)
        ALLOW_DB_AHEAD=true
        shift
        ;;
      --i-accept-forward-only-db)
        ACCEPT_FORWARD_ONLY_DB=true
        shift
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        log_error "Unknown argument: $1"
        usage
        exit 1
        ;;
    esac
  done

  if [[ "$VERIFY_ONLY" == "true" ]]; then
    verify_only
    exit 0
  fi

  local current_sha
  current_sha="$(git rev-parse HEAD)"
  local target_sha
  target_sha="$(resolve_target_sha)"
  local target_mode
  target_mode="$(resolve_target_mode)"
  local target_color
  target_color="$(resolve_target_color)"

  if [[ "$target_mode" == "blue-green" && -z "$target_color" ]]; then
    log_error "Deploy state missing deploy_color for blue/green rollback."
    exit 1
  fi

  echo ""
  echo "=========================================="
  echo "          Rollback Initiated              "
  echo "=========================================="
  echo ""
  log_info "From SHA: $current_sha"
  log_info "To SHA:   $target_sha"
  log_info "Mode:     $target_mode"
  if [[ -n "$target_color" ]]; then
    log_info "Color:    $target_color"
  fi

  if [[ "$DRY_RUN" == "true" ]]; then
    log_warn "Dry-run mode enabled. No changes will be applied."
  fi

  reset_repo_to_sha "$target_sha"

  local expected_heads
  if [[ "$target_mode" == "blue-green" ]]; then
    expected_heads="$(fetch_expected_heads "api-${target_color}" "${COMPOSE_BLUE_GREEN[@]}")"
  else
    expected_heads="$(fetch_expected_heads "api" "${COMPOSE_STANDARD[@]}")"
  fi
  local current_revision
  if [[ "$target_mode" == "blue-green" ]]; then
    current_revision="$(fetch_db_revision "${COMPOSE_BLUE_GREEN[@]}")"
  else
    current_revision="$(fetch_db_revision "${COMPOSE_STANDARD[@]}")"
  fi

  log_info "Migration heads (target code): ${expected_heads:-unknown}"
  log_info "Current DB revision: ${current_revision:-unknown}"

  if [[ "$target_mode" == "blue-green" ]]; then
    rollback_blue_green "$target_sha" "$target_color" "$expected_heads" "$current_revision"
  else
    rollback_standard "$target_sha" "$expected_heads" "$current_revision"
  fi

  record_rollback_event "$current_sha" "$target_sha" "$target_mode"

  log_success "Rollback completed successfully."
}

main "$@"
