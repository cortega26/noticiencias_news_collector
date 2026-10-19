#!/usr/bin/env bash
# Plan 151 smoke: the serving image must answer its routes honestly.
#
# Builds Dockerfile.serving and runs it the way the hosted tier does
# (production environment tier, ADMIN_API_KEY set), then checks:
#   /healthz                        -> 200
#   /v1/admin/analytics             -> 200
#   GET  /v1/admin/content          -> 503 + error_code=published_content_unavailable
#   DELETE /v1/admin/content/{id}   -> 503 + the same body
#   POST /v1/admin/content/bulk-reset -> 503 + the same body
#
# The image ships no git binary and no frontend checkout, so the three
# published-content routes are a local-admin capability: they must say so with
# a stable 503 instead of today's ImportError-driven 500.
#
# Not wired into CI yet — plan 151 records that as a follow-up. Local proof:
#   bash scripts/smoke_serving_image.sh
# Reuse an already-built image (no rebuild):
#   SKIP_BUILD=1 IMAGE=nc-serving:plan151 bash scripts/smoke_serving_image.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="${IMAGE:-nc-serving:smoke}"
PORT="${PORT:-8125}"
CONTAINER_NAME="${CONTAINER_NAME:-nc-serving-smoke}"
ADMIN_TOKEN="${ADMIN_TOKEN:-test}"
WAIT_SECONDS="${WAIT_SECONDS:-60}"

cd "$REPO_ROOT"

cleanup() {
  docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
}
trap cleanup EXIT

if [[ "${SKIP_BUILD:-0}" != "1" ]]; then
  echo "[smoke] building ${IMAGE} from Dockerfile.serving"
  docker build -f Dockerfile.serving -t "$IMAGE" .
fi

cleanup
echo "[smoke] starting ${IMAGE} on port ${PORT}"
docker run -d --name "$CONTAINER_NAME" \
  -e "ADMIN_API_KEY=${ADMIN_TOKEN}" \
  -p "${PORT}:8000" "$IMAGE" >/dev/null

health=""
for _ in $(seq 1 "$WAIT_SECONDS"); do
  health="$(curl -s -o /dev/null -w '%{http_code}' "localhost:${PORT}/healthz" || true)"
  if [[ "$health" == "200" ]]; then
    break
  fi
  sleep 1
done
if [[ "$health" != "200" ]]; then
  echo "[smoke] FAIL: /healthz never answered 200 (last: ${health})"
  docker logs "$CONTAINER_NAME" 2>&1 | tail -20
  exit 1
fi

failures=0

request() {  # method path [data]
  local method="$1" path="$2" data="${3:-}"
  if [[ -n "$data" ]]; then
    curl -s -w '\n%{http_code}' -X "$method" \
      -H "Authorization: Bearer ${ADMIN_TOKEN}" \
      -H 'Content-Type: application/json' \
      -d "$data" \
      "localhost:${PORT}${path}"
  else
    curl -s -w '\n%{http_code}' -X "$method" \
      -H "Authorization: Bearer ${ADMIN_TOKEN}" \
      "localhost:${PORT}${path}"
  fi
}

expect_status() {  # method path expected [data]
  local method="$1" path="$2" expected="$3" data="${4:-}"
  local raw code body
  raw="$(request "$method" "$path" "$data")"
  code="$(printf '%s' "$raw" | tail -n1)"
  body="$(printf '%s' "$raw" | sed '$d')"
  if [[ "$code" != "$expected" ]]; then
    echo "[smoke] FAIL: ${method} ${path} -> ${code} (expected ${expected}): ${body}"
    failures=$((failures + 1))
  else
    echo "[smoke] ok: ${method} ${path} -> ${code}"
  fi
}

expect_capability_503() {  # method path [data]
  local method="$1" path="$2" data="${3:-}"
  local raw code body
  raw="$(request "$method" "$path" "$data")"
  code="$(printf '%s' "$raw" | tail -n1)"
  body="$(printf '%s' "$raw" | sed '$d')"
  if [[ "$code" != "503" ]]; then
    echo "[smoke] FAIL: ${method} ${path} -> ${code} (expected 503): ${body}"
    failures=$((failures + 1))
    return
  fi
  if [[ "$body" != *"published_content_unavailable"* ]]; then
    echo "[smoke] FAIL: ${method} ${path} 503 without the error_code: ${body}"
    failures=$((failures + 1))
    return
  fi
  if [[ "$body" == *"Traceback"* || "$body" == *"  File \""* || "$body" == *"Internal Server Error"* ]]; then
    echo "[smoke] FAIL: ${method} ${path} body leaks a traceback: ${body}"
    failures=$((failures + 1))
    return
  fi
  echo "[smoke] ok: ${method} ${path} -> 503 published_content_unavailable"
}

expect_status GET /healthz 200
expect_status GET /v1/admin/analytics 200
expect_capability_503 GET /v1/admin/content
expect_capability_503 DELETE /v1/admin/content/smoke-check
expect_capability_503 POST /v1/admin/content/bulk-reset '{"refinery_ids":["smoke-check"]}'

if [[ "$failures" -ne 0 ]]; then
  echo "[smoke] FAIL: ${failures} check(s) failed"
  docker logs "$CONTAINER_NAME" 2>&1 | tail -20
  exit 1
fi

echo "[smoke] OK: the serving image answers health/analytics and reports published content as unavailable"
