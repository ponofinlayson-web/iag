#!/usr/bin/env bash
# Fault-tolerance smoke test for an ISOLATED (renamed-container) IAG stack.
# Identical contract to scripts/smoke.sh (architecture contract #6):
#   kill one app replica mid-service -> nginx keeps serving -> audit chain
#   still verifies -> replica restarts and rejoins.
# Difference: every docker reference honors env overrides so a cloned stack
# (e.g. compose.test.yaml: project iag-test, containers iag-test-*) can be
# proven without touching the original deployment.
#   BASE_URL=http://localhost:8091 IAG_APP2_CONTAINER=iag-test-app-2 \
#   COMPOSE_PROJECT_NAME=iag-test COMPOSE_FILE=compose.yaml;compose.test.yaml \
#   bash scripts/smoke.test.sh
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8090}"
ADMIN_USER="${IAG_BOOTSTRAP_ADMIN_USERNAME:-admin}"
APP2="${IAG_APP2_CONTAINER:-iag-app-2}"

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
docker compose -p iag-test -f "$(dirname "$0")/../compose.yaml" -f "$(dirname "$0")/../compose.test.yaml" ps

say "1. service is up through nginx (3 replicas)"
curl -fsS "$BASE_URL/api/health" | grep -q '"status"'
curl -fsS "$BASE_URL/" | grep -q 'id="root"'

say "2. login + audit chain verifies"
curl -fsS -c /tmp/iag_smoke_test.jar \
  -H 'Content-Type: application/json' \
  -d "{\"username\":\"$ADMIN_USER\",\"password\":\"$IAG_BOOTSTRAP_ADMIN_PASSWORD\"}" \
  "$BASE_URL/api/auth/login" | grep -q '"ok":true'
curl -fsS -b /tmp/iag_smoke_test.jar "$BASE_URL/api/audit/verify" | grep -q '"valid":true'

say "3. kill $APP2"
docker stop "$APP2" >/dev/null
sleep 2

say "4. service must survive via nginx"
curl -fsS "$BASE_URL/api/health" | grep -q '"status"' \
  || fail "health died with $APP2 (LB failover broken)"
curl -fsS -b /tmp/iag_smoke_test.jar "$BASE_URL/api/dashboard" >/dev/null \
  || fail "dashboard died with $APP2"

say "5. audit chain still verifies through the survivors"
curl -fsS -b /tmp/iag_smoke_test.jar "$BASE_URL/api/audit/verify" | grep -q '"valid":true' \
  || fail "audit chain broken after replica kill"

say "6. restart $APP2 and wait for it to rejoin"
docker start "$APP2" >/dev/null
for i in $(seq 1 30); do
  if docker inspect -f '{{.State.Health.Status}}' "$APP2" 2>/dev/null | grep -q healthy; then
    break
  fi
  sleep 2
done
docker inspect -f '{{.State.Health.Status}}' "$APP2" | grep -q healthy \
  || fail "$APP2 did not return to healthy"

say "7. full service after rejoin"
curl -fsS "$BASE_URL/api/health" | grep -q '"status"'

say "SMOKE PASS (isolated stack) — resilience contract held"
