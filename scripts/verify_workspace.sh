#!/usr/bin/env bash
#
# verify_workspace.sh — Plan 041 cross-repo workspace verification.
#
# Runs both repo-level canonical gates (backend `make verify-ci` and
# frontend `npm run verify:ci`) plus a read-only cross-repo publication
# scenario (schema parity, contract sync). Never publishes, pushes,
# modifies real content, or uses secrets.
#
# Usage:
#   ./scripts/verify_workspace.sh --backend . --frontend ../noticiencias
#   ./scripts/verify_workspace.sh --backend . --frontend ../noticiencias --backend-schema path/to/schema.py
#
# Exits 0 on success, non-zero on failure.

set -u

BACKEND="."
FRONTEND=""
BACKEND_SCHEMA=""

usage() {
  echo "Usage: $0 --backend <path> --frontend <path> [--backend-schema <path>]"
  echo "  --backend PATH        Backend repo root (default: .)"
  echo "  --frontend PATH       Frontend repo root (required)"
  echo "  --backend-schema PATH Override backend schema path for contract sync"
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --backend) BACKEND="$2"; shift 2 ;;
    --frontend) FRONTEND="$2"; shift 2 ;;
    --backend-schema) BACKEND_SCHEMA="$2"; shift 2 ;;
    -h|--help) usage ;;
    *) echo "Unknown option: $1"; usage ;;
  esac
done

[ -d "$BACKEND" ] || { echo "ERROR: backend dir not found: $BACKEND"; exit 1; }
[ -n "$FRONTEND" ] || { echo "ERROR: --frontend is required"; exit 1; }
[ -d "$FRONTEND" ] || { echo "ERROR: frontend dir not found: $FRONTEND"; exit 1; }

BACKEND="$(cd "$BACKEND" && pwd)"
FRONTEND="$(cd "$FRONTEND" && pwd)"

echo "═══════════════════════════════════════════════════════════"
echo "  Workspace Verification (plan 041)"
echo "  Backend:  $BACKEND"
echo "  Frontend: $FRONTEND"
echo "═══════════════════════════════════════════════════════════"

# ── 0. Verify clean working trees ─────────────────────────────────────────
echo
echo "── Step 0: Verify clean working trees ──"

BACKEND_DIRTY="$(cd "$BACKEND" && git status --short 2>/dev/null | head -1)"
FRONTEND_DIRTY="$(cd "$FRONTEND" && git status --short 2>/dev/null | head -1)"

if [ -n "$BACKEND_DIRTY" ]; then
  echo "ERROR: Backend has uncommitted changes:"
  (cd "$BACKEND" && git status --short)
  echo "Commit or stash changes before running workspace verification."
  exit 1
fi
if [ -n "$FRONTEND_DIRTY" ]; then
  echo "ERROR: Frontend has uncommitted changes:"
  (cd "$FRONTEND" && git status --short)
  echo "Commit or stash changes before running workspace verification."
  exit 1
fi
echo "  ✓ Both repos clean"

# ── 1. Backend canonical gate ────────────────────────────────────────────
echo
echo "── Step 1: Backend make verify-ci ──"
if ! (cd "$BACKEND" && make verify-ci); then
  echo "ERROR: Backend verify-ci failed"
  exit 1
fi
echo "  ✓ Backend verify-ci passed"

# ── 2. Frontend canonical gate ───────────────────────────────────────────
echo
echo "── Step 2: Frontend npm run verify:ci ──"
if ! (cd "$FRONTEND" && npm run verify:ci); then
  # Tolerate the pre-existing validate:content freeze-template condition
  echo "  NOTE: If verify:ci failed on validate:content (ReportForm.astro),"
  echo "  that is a pre-existing baseline condition (plan 023 unpushed)."
  echo "ERROR: Frontend verify:ci failed"
  exit 1
fi
echo "  ✓ Frontend verify:ci passed"

# ── 3. Cross-repo contract parity ────────────────────────────────────────
echo
echo "── Step 3: Cross-repo contract parity ──"
SCHEMA_PATH="${BACKEND_SCHEMA:-$BACKEND/news_collector/contracts/frontend_schema.py}"
if [ ! -f "$SCHEMA_PATH" ]; then
  echo "ERROR: Backend schema not found: $SCHEMA_PATH"
  exit 1
fi
if ! (cd "$FRONTEND" && BACKEND_SCHEMA_PATH="$SCHEMA_PATH" npm run check:contract-sync); then
  echo "ERROR: Contract sync failed — backend and frontend schemas are out of parity"
  exit 1
fi
echo "  ✓ Contract parity verified"

# ── 4. Verify both repos still clean (read-only proof) ──────────────────
echo
echo "── Step 4: Verify repos unchanged (read-only proof) ──"
BACKEND_AFTER="$(cd "$BACKEND" && git status --short 2>/dev/null | head -1)"
FRONTEND_AFTER="$(cd "$FRONTEND" && git status --short 2>/dev/null | head -1)"
if [ -n "$BACKEND_AFTER" ]; then
  echo "ERROR: Backend git status changed during verification:"
  (cd "$BACKEND" && git status --short)
  exit 1
fi
if [ -n "$FRONTEND_AFTER" ]; then
  echo "ERROR: Frontend git status changed during verification:"
  (cd "$FRONTEND" && git status --short)
  exit 1
fi
echo "  ✓ Both repos unchanged — workspace verification is read-only"

echo
echo "═══════════════════════════════════════════════════════════"
echo "  ✓ Workspace verification PASSED"
echo "═══════════════════════════════════════════════════════════"
