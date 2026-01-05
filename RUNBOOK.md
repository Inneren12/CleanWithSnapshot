# Incident Runbook

## Check
- curl -fsS https://api.panidobro.com/healthz
- cd /opt/cleaning && docker compose ps

## Logs
- docker compose logs --tail=200 api
- docker compose logs --tail=200 caddy
- docker compose logs --tail=200 db

## Quick fixes
- docker compose restart api
- docker compose restart caddy
- docker compose restart db

## Disk/RAM
- df -h
- free -m

## Deploy
- /opt/cleaning/deploy.sh
