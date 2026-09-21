#!/usr/bin/env bash
#
# Run the full Refinery admin stack for local development:
#   - serving API  (FastAPI, uvicorn --reload, :8000)
#   - admin GUI    (Astro dev server, :4321; proxies /v1/* to the API)
#
# One Ctrl+C tears down both. Invoked by `make admin`.
#
# Env:
#   PYTHON_BIN        python interpreter for the API (default: .venv/bin/python)
#   ADMIN_API_TARGET  where the GUI proxy sends /v1/* (default: follows the
#                     chosen API port, i.e. http://localhost:$API_PORT)
#   API_PORT          preferred API port (default: 8000)
#   GUI_PORT          preferred GUI port (default: 4321)
#
# Port policy: defaults are resilient — if the preferred port is busy the
# stack bumps to the next free one (scan capped at +100) and the GUI proxy
# follows the chosen API port automatically, so everything still works.
# Explicitly exported ports are honored strictly instead: if API_PORT=9000
# is busy the script dies rather than silently running elsewhere.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$repo_root"

python_bin="${PYTHON_BIN:-.venv/bin/python}"
astro_bin="node_modules/.bin/astro"

API_PORT_DEFAULT=8000
GUI_PORT_DEFAULT=4321
PORT_SCAN_RANGE=100

if [[ -n "${API_PORT+x}" ]]; then API_EXPLICIT=1; else API_PORT=$API_PORT_DEFAULT; API_EXPLICIT=0; fi
if [[ -n "${GUI_PORT+x}" ]]; then GUI_EXPLICIT=1; else GUI_PORT=$GUI_PORT_DEFAULT; GUI_EXPLICIT=0; fi

die() { echo "admin-stack: $*" >&2; exit 1; }

[[ -x "$python_bin" ]] || die "python interpreter not found at '$python_bin' — run 'make bootstrap' first"
[[ -d apps/admin/node_modules ]] || die "apps/admin/node_modules missing — run 'make admin-install' first"

port_busy() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null && { exec 3>&- 3<&-; return 0; } || return 1; }

valid_port() { [[ "$1" =~ ^[0-9]+$ ]] && (( $1 >= 1 && $1 <= 65535 )); }

# Echo the first free TCP port at or above $1 (scans +$PORT_SCAN_RANGE).
pick_free_port() {
  local port=$1 limit=$(( $1 + PORT_SCAN_RANGE ))
  while (( port <= limit )); do
    port_busy "$port" || { echo "$port"; return 0; }
    port=$(( port + 1 ))
  done
  return 1
}

# Resolve a preferred port: explicit values are strict (busy = failure),
# defaults fall forward to the next free port with a loud notice.
# Echoes the chosen port; returns nonzero with no output on failure so the
# caller (not a subshell) decides how to die.
resolve_port() {
  local label=$1 wanted=$2 explicit=$3 chosen
  if ! port_busy "$wanted"; then
    echo "$wanted"
    return 0
  fi
  if (( explicit )); then
    return 1
  fi
  chosen=$(pick_free_port "$wanted") || return 1
  echo "[admin-stack] NOTE: preferred $label port $wanted is busy — using $chosen" >&2
  echo "$chosen"
  return 0
}

valid_port "$API_PORT" || die "API_PORT='$API_PORT' is not a valid TCP port (1-65535)"
valid_port "$GUI_PORT" || die "GUI_PORT='$GUI_PORT' is not a valid TCP port (1-65535)"

# Never stomp something already listening on an *explicit* port — the user
# may have `make serve` running on purpose in a second terminal. Defaults
# just move forward instead of dying (the old behavior).
API_PORT=$(resolve_port "API" "$API_PORT" "$API_EXPLICIT") \
  || die "API port $API_PORT is already in use — stop the other process first (or unset API_PORT to auto-pick a free one)."
GUI_PORT=$(resolve_port "GUI" "$GUI_PORT" "$GUI_EXPLICIT") \
  || die "GUI port $GUI_PORT is already in use — stop it first (Ctrl+C in its terminal, or 'cd apps/admin && npx astro dev stop')."

# The two services must never share a port. Overlapping overrides (e.g.
# API_PORT=4321) resolve identically because nothing listens yet, so the
# API would claim the port and the GUI would fail to bind. Bump the
# non-explicit side; two explicitly equal ports are unsatisfiable.
while [[ "$GUI_PORT" == "$API_PORT" ]]; do
  if (( API_EXPLICIT && GUI_EXPLICIT )); then
    die "API_PORT and GUI_PORT both resolve to $API_PORT — give each service its own port."
  elif (( GUI_EXPLICIT )); then
    API_PORT=$(pick_free_port $(( API_PORT + 1 ))) \
      || die "no free API port above $API_PORT (GUI pinned to $GUI_PORT)."
    echo "[admin-stack] NOTE: API port collided with pinned GUI port — using $API_PORT" >&2
  else
    GUI_PORT=$(pick_free_port $(( GUI_PORT + 1 ))) \
      || die "no free GUI port above $GUI_PORT (API on $API_PORT)."
    echo "[admin-stack] NOTE: GUI port collided with API port $API_PORT — using $GUI_PORT" >&2
  fi
done

# The GUI proxy must follow the chosen API port, unless the operator pinned
# ADMIN_API_TARGET themselves (then it is their wiring — just show it).
if [[ -z "${ADMIN_API_TARGET+x}" ]]; then
  export ADMIN_API_TARGET="http://localhost:${API_PORT}"
fi
echo "[admin-stack] API  : http://localhost:${API_PORT}"
echo "[admin-stack] GUI  : http://localhost:${GUI_PORT}  (proxy /v1/* -> ${ADMIN_API_TARGET})"
case "$ADMIN_API_TARGET" in
  *":${API_PORT}"*|*"${API_PORT}/"*) ;;
  *) echo "[admin-stack] WARNING: ADMIN_API_TARGET ($ADMIN_API_TARGET) does not point at the API port ($API_PORT) — /v1/* calls will fail." >&2 ;;
esac

api_pid=""
cleanup() {
  trap - INT TERM EXIT
  set +e
  if [[ -n "$api_pid" ]]; then
    kill -TERM "-$api_pid" 2>/dev/null
    for _ in 1 2 3 4 5 6; do
      kill -0 "-$api_pid" 2>/dev/null || break
      sleep 1
    done
    kill -KILL "-$api_pid" 2>/dev/null
  fi
  # Only stops a GUI this script started (it holds the lock by then); an
  # explicitly-pinned GUI port belonging to someone else is rejected above,
  # so this never kills someone else's.
  ( cd apps/admin && "$astro_bin" dev stop >/dev/null 2>&1 )
  wait 2>/dev/null
  echo "[admin-stack] stopped."
}
trap cleanup INT TERM EXIT

# API in the background, in its own process group (uvicorn --reload spawns a
# reloader child; the negative-pid kill in cleanup reaps the whole group).
echo "[admin-stack] starting serving API on :${API_PORT} ..."
SERVING_PORT="$API_PORT" NEWS_COLLECTOR_PATH="$repo_root" setsid "$python_bin" -m news_collector.serving &
api_pid=$!

# Wait for the API to actually accept connections before starting the GUI, so
# its first proxied request doesn't race the boot.
for _ in $(seq 1 40); do
  kill -0 "$api_pid" 2>/dev/null || die "serving API exited during startup (see output above)"
  port_busy "$API_PORT" && break
  sleep 0.5
done
port_busy "$API_PORT" || die "serving API did not open port $API_PORT within 20s"

# GUI in the foreground: for an interactive shell this blocks until Ctrl+C,
# which hits this script and fires the trap. Astro auto-backgrounds itself
# inside AI-agent environments — handled just below.
echo "[admin-stack] starting admin GUI on :${GUI_PORT}  (Ctrl+C stops both)"
( cd apps/admin && npm run dev -- --port "$GUI_PORT" ) || true

# Reached only if the GUI returned on its own. If Astro backgrounded it, keep
# the API alive and block on it instead of tearing the stack down.
if ( cd apps/admin && "$astro_bin" dev status 2>/dev/null | grep -qi "running" ); then
  echo "[admin-stack] GUI running in the background — Ctrl+C stops everything"
  wait "$api_pid"
fi
