#!/bin/bash
set -e

ROOT="${ROOT:-/home/chulk/CleanWithSnapshot}"
cd "$ROOT"
# If node is not available, try to load nvm (no sudo/apt).
if ! command -v node >/dev/null 2>&1; then
  export NVM_DIR="$HOME/.nvm"
  if [ -s "$NVM_DIR/nvm.sh" ]; then
    . "$NVM_DIR/nvm.sh"
    # Use whatever is available; prefer 20 if installed.
    if command -v nvm >/dev/null 2>&1; then
      nvm use 20 >/dev/null 2>&1 || nvm use default >/dev/null 2>&1 || true
    fi
  fi
fi

# Guardrails: no sudo/apt, no OS installs (script should be safe in limited envs)
# This script assumes node/pnpm are already available.
echo "Repo: $(pwd)"
echo "Node: $(node -v)"
echo "pnpm: $(pnpm -v)"

# Env file handling
python3 scripts/generate_e2e_env.py
if [ -f "e2e_env_vars.sh" ]; then
    source e2e_env_vars.sh
else
    echo "ERROR: e2e_env_vars.sh missing!"
    exit 1
fi

# Compose files: mirror CI pattern (workflow is in .github/workflows/e2e.yml)
COMPOSE_BASE="docker-compose.yml"
COMPOSE_E2E="docker-compose.e2e.yml"
COMPOSE_OVERRIDE="docker-compose.e2e.override.yml"

if [ ! -f "$COMPOSE_BASE" ]; then
  echo "ERROR: $COMPOSE_BASE not found in repo root."
  exit 1
fi
if [ ! -f "$COMPOSE_E2E" ]; then
  echo "ERROR: $COMPOSE_E2E not found in repo root."
  exit 1
fi
if [ ! -f "$COMPOSE_OVERRIDE" ]; then
  echo "ERROR: $COMPOSE_OVERRIDE not found in repo root."
  echo "Create it first (E2E-only overrides)."
  exit 1
fi

# Bring up stack similar to CI.
# Include web+caddy because PLAYWRIGHT_BASE_URL points to :3000.
echo "Starting services (api, web, jobs, caddy; plus db/redis if present)..."
set +e
docker compose -f "$COMPOSE_BASE" -f "$COMPOSE_E2E" -f "$COMPOSE_OVERRIDE" up -d --build api web jobs caddy db redis
status=$?
set -e
if [ $status -ne 0 ]; then
  echo "ERROR: docker compose up failed with status $status"
  docker compose -f "$COMPOSE_BASE" -f "$COMPOSE_E2E" -f "$COMPOSE_OVERRIDE" ps || true
  docker compose -f "$COMPOSE_BASE" -f "$COMPOSE_E2E" -f "$COMPOSE_OVERRIDE" logs --no-color --tail=200 api || true
  docker compose -f "$COMPOSE_BASE" -f "$COMPOSE_E2E" -f "$COMPOSE_OVERRIDE" logs --no-color --tail=200 web || true
  docker compose -f "$COMPOSE_BASE" -f "$COMPOSE_E2E" -f "$COMPOSE_OVERRIDE" logs --no-color --tail=200 jobs || true
  exit $status
fi


cd web
echo "=== Running Playwright Tests ==="
if command -v google-chrome &> /dev/null; then
    export PW_CHANNEL=chrome
else
    export PW_CHANNEL=chromium
fi

export PLAYWRIGHT_BASE_URL=http://127.0.0.1:3000
export PLAYWRIGHT_API_BASE_URL=http://127.0.0.1:8000

# NOTE: Do not force ADMIN_PROXY_AUTH_E2E_ENABLED here.
# If you want to control it, do it via docker-compose.e2e.override.yml (source of truth).

pnpm exec playwright test --config e2e/playwright.config.ts
