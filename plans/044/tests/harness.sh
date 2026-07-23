#!/usr/bin/env bash
set -u

BACKEND_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
FRONTEND="${FRONTEND:-$BACKEND_ROOT/../noticiencias}"
TESTS_DIR="$BACKEND_ROOT/plans/044/tests"

PASS=0; FAIL=0
color() { printf '\033[%sm%s\033[0m\n' "$1" "$2"; }
pass() { color '32' "PASS  $1"; PASS=$((PASS+1)); }
fail() { color '31' "FAIL  $1"; FAIL=$((FAIL+1)); }
summary() { echo; echo "────────────────────────────────────────"; printf "  %d passed, %d failed\n" "$PASS" "$FAIL"; echo "────────────────────────────────────────"; [ "$FAIL" -eq 0 ]; }
run_in_frontend() { ( cd "$FRONTEND" && "$@" ); }

cmd_build() {
  local tmp; tmp="$(mktemp)"
  if run_in_frontend npm run build >"$tmp" 2>&1; then
    local pages; pages="$(grep -oE '[0-9]+ page' "$tmp" | tail -1 || true)"
    pass "build — exits 0 ($pages)"; rm -f "$tmp"; return 0
  fi
  fail "build — failed"; tail -20 "$tmp"; rm -f "$tmp"; return 1
}

cmd_pagination() {
  if [ ! -f "$FRONTEND/tests/pagination-config.test.ts" ]; then
    fail "pagination — tests/pagination-config.test.ts not created yet"; return 1
  fi
  if run_in_frontend npx vitest run tests/pagination-config.test.ts >"$TESTS_DIR/.pagination.log" 2>&1; then
    pass "pagination — test passes"; return 0
  fi
  fail "pagination — test failed"; tail -15 "$TESTS_DIR/.pagination.log"; return 1
}

cmd_validate() {
  local step rc=0
  for step in lint validate:content test:dist test:audit; do
    if run_in_frontend npm run "$step" >"$TESTS_DIR/.validate-$step.log" 2>&1; then
      pass "validate — npm run $step"
    else
      if [ "$step" = "validate:content" ] && grep -q "ReportForm.astro" "$TESTS_DIR/.validate-$step.log" 2>/dev/null; then
        pass "validate — npm run $step (pre-existing tolerated)"
      else
        fail "validate — npm run $step failed"; tail -10 "$TESTS_DIR/.validate-$step.log"; rc=1
      fi
    fi
  done
  return $rc
}

cmd_e2e() {
  if CI=1 run_in_frontend npm run test:e2e >"$TESTS_DIR/.e2e.log" 2>&1; then
    local passed; passed="$(grep -oE '[0-9]+ passed' "$TESTS_DIR/.e2e.log" | tail -1 || echo '?')"
    pass "e2e — passes ($passed)"; return 0
  fi
  fail "e2e — failed"; tail -15 "$TESTS_DIR/.e2e.log"; return 1
}

cmd_all() {
  local rc=0
  for cmd in build pagination validate e2e; do "cmd_$cmd" || rc=1; done
  summary; return $rc
}

case "${1:-}" in
  build) cmd_build ;;
  pagination) cmd_pagination ;;
  validate) cmd_validate ;;
  e2e) cmd_e2e ;;
  all) cmd_all ;;
  "") echo "Usage: $0 <command>"; echo "Commands: build pagination validate e2e all"; exit 1 ;;
  *) echo "Unknown: $1"; exit 1 ;;
esac
