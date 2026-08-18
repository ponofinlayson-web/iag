#!/usr/bin/env bash
# IAG fault-tolerance smoke test (architecture contract #6):
#   kill one app replica mid-service -> nginx keeps serving -> audit chain
#   still verifies -> replica restarts and rejoins.
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8090}"
ADMIN_USER="${IAG_BOOTSTRAP_ADMIN_USERNAME:-admin}"

# Secrets come from the gitignored .env (same file compose uses); never
# hardcoded here. Password has NO fallback: fail loud if .env is missing.
ENV_FILE="${ENV_FILE:-$(dirname "$0")/../.env}"
if [ -f "$ENV_FILE" ]; then
  # shellcheck disable=SC1090
  . "$ENV_FILE"
fi
: "${IAG_BOOTSTRAP_ADMIN_PASSWORD:?IAG_BOOTSTRAP_ADMIN_PASSWORD missing (set it in .env; see .env.example)}"

say()  { printf '\n== %s\n' "$*"; }
fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }

command -v docker >/dev/null || fail "docker CLI not found"

say "stack state"
docker compose ps

say "1. service is up through nginx (3 replicas)"
curl -fsS "$BASE_URL/api/health" | grep -q '"status"'
curl -fsS "$BASE_URL/" | grep -q 'id="root"'

say "2. login + audit chain verifies"
curl -fsS -c /tmp/iag_smoke.jar \
  -H 'Content-Type: application/json' \
  -d "{\"username\":\"$ADMIN_USER\",\"password\":\"$IAG_BOOTSTRAP_ADMIN_PASSWORD\"}" \
  "$BASE_URL/api/auth/login" | grep -q '"ok":true'
curl -fsS -b /tmp/iag_smoke.jar "$BASE_URL/api/audit/verify" | grep -q '"valid":true'

say "3. kill iag-app-2"
docker stop iag-app-2 >/dev/null
sleep 2

say "4. service must survive via nginx"
curl -fsS "$BASE_URL/api/health" | grep -q '"status"' \
  || fail "health died with app-2 (LB failover broken)"
curl -fsS -b /tmp/iag_smoke.jar "$BASE_URL/api/dashboard" >/dev/null \
  || fail "dashboard died with app-2"

say "5. audit chain still verifies through the survivors"
curl -fsS -b /tmp/iag_smoke.jar "$BASE_URL/api/audit/verify" | grep -q '"valid":true' \
  || fail "audit chain broken after replica kill"

say "6. restart iag-app-2 and wait for it to rejoin"
docker start iag-app-2 >/dev/null
for i in $(seq 1 30); do
  if docker inspect -f '{{.State.Health.Status}}' iag-app-2 2>/dev/null | grep -q healthy; then
    break
  fi
  sleep 2
done
docker inspect -f '{{.State.Health.Status}}' iag-app-2 | grep -q healthy \
  || fail "app-2 did not return to healthy"

say "7. full service after rejoin"
curl -fsS "$BASE_URL/api/health" | grep -q '"status"'

say "SMOKE PASS — resilience contract held"
