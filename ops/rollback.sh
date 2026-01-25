#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
cd "$REPO_ROOT"

STATE_DIR="$REPO_ROOT/ops/state"
LAST_GOOD_FILE="$STATE_DIR/last_good.env"
CADDY_UPSTREAM_DIR="$REPO_ROOT/config/caddy"
COMPOSE_STANDARD=(docker compose)
COMPOSE_BLUE_GREEN=(docker compose -f docker-compose.yml -f docker-compose.blue-green.yml)

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

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

load_last_good() {
  if [[ ! -f "$LAST_GOOD_FILE" ]]; then
    log_error "Last known good file not found: $LAST_GOOD_FILE"
    log_error "Run ./ops/deploy.sh or ./ops/blue-green-deploy.sh first to record a good release."
    exit 1
  fi

  set -a
  # shellcheck source=/dev/null
  source "$LAST_GOOD_FILE"
  set +a

  if [[ -z "${LAST_GOOD_SHA:-}" ]]; then
    log_error "LAST_GOOD_SHA is missing in $LAST_GOOD_FILE"
    exit 1
  fi
}

record_last_good() {
  local sha="$1"
  local mode="$2"
  local color="${3:-}"
  local timestamp
  timestamp="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

  mkdir -p "$STATE_DIR"
  cat > "$LAST_GOOD_FILE" <<EOF
LAST_GOOD_SHA=$sha
LAST_GOOD_MODE=$mode
LAST_GOOD_COLOR=$color
LAST_GOOD_TIMESTAMP=$timestamp
EOF
}

reset_repo_to_sha() {
  local sha="$1"

  log_info "Fetching latest origin refs..."
  git fetch origin

  log_info "Resetting repo to last known good SHA: $sha"
  git reset --hard "$sha"

  git clean -xfd \
    -e ".env" \
    -e "logs/" \
    -e "var/" \
    -e "tmp/" \
    -e "pg_data/" \
    -e "caddy_data/" \
    -e "caddy_config/" \
    -e "ops/state/last_good.env"
}

update_caddy_upstream() {
  local color="$1"
  local upstream_file="$CADDY_UPSTREAM_DIR/upstream-${color}.caddy"
  local active_file="$CADDY_UPSTREAM_DIR/active-upstream.caddy"

  if [[ ! -f "$upstream_file" ]]; then
    log_error "Upstream config not found: $upstream_file"
    return 1
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

  log_info "Updated Caddy upstream configuration to: $color"
}

reload_caddy() {
  local -a compose_cmd=("$@")

  log_info "Reloading Caddy configuration..."
  if "${compose_cmd[@]}" exec -T caddy caddy reload --config /etc/caddy/Caddyfile 2>/dev/null; then
    log_success "Caddy configuration reloaded"
  else
    log_warn "Caddy reload failed, restarting container..."
    "${compose_cmd[@]}" restart caddy
    sleep 5
  fi
}

rollback_standard() {
  reset_repo_to_sha "$LAST_GOOD_SHA"

  log_info "Building images..."
  "${COMPOSE_STANDARD[@]}" build

  log_info "Starting services..."
  "${COMPOSE_STANDARD[@]}" up -d --remove-orphans

  log_info "Running smoke tests..."
  "$REPO_ROOT/ops/smoke.sh"

  record_last_good "$LAST_GOOD_SHA" "standard"

  log_success "Rollback completed successfully (standard stack)."
}

rollback_blue_green() {
  local color="$1"

  reset_repo_to_sha "$LAST_GOOD_SHA"

  log_info "Building images for $color stack..."
  "${COMPOSE_BLUE_GREEN[@]}" build "api-${color}" "web-${color}"

  log_info "Starting $color stack services..."
  "${COMPOSE_BLUE_GREEN[@]}" up -d "api-${color}" "web-${color}" caddy

  update_caddy_upstream "$color"
  reload_caddy "${COMPOSE_BLUE_GREEN[@]}"

  mkdir -p "$STATE_DIR"
  echo "$color" > "$STATE_DIR/active_color"

  log_info "Running smoke tests..."
  "$REPO_ROOT/ops/smoke.sh"

  record_last_good "$LAST_GOOD_SHA" "blue-green" "$color"

  log_success "Rollback completed successfully (blue/green stack)."
}

main() {
  load_last_good

  echo ""
  echo "=========================================="
  echo "          Rollback Initiated              "
  echo "=========================================="
  echo ""

  log_info "Last known good SHA: $LAST_GOOD_SHA"
  log_info "Last known good mode: ${LAST_GOOD_MODE:-standard}"

  if [[ "${LAST_GOOD_MODE:-standard}" == "blue-green" ]]; then
    if [[ -z "${LAST_GOOD_COLOR:-}" ]]; then
      log_error "LAST_GOOD_COLOR is missing for blue-green rollback."
      exit 1
    fi
    rollback_blue_green "$LAST_GOOD_COLOR"
  else
    rollback_standard
  fi
}

main "$@"
