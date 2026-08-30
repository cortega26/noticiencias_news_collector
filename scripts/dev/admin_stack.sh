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
#   ADMIN_API_TARGET  where the GUI proxy sends /v1/* (default: http://localhost:8000)
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$repo_root"

python_bin="${PYTHON_BIN:-.venv/bin/python}"
astro_bin="node_modules/.bin/astro"
API_PORT=8000
GUI_PORT=4321

die() { echo "admin-stack: $*" >&2; exit 1; }

[[ -x "$python_bin" ]] || die "python interpreter not found at '$python_bin' — run 'make bootstrap' first"
[[ -d apps/admin/node_modules ]] || die "apps/admin/node_modules missing — run 'make admin-install' first"

port_busy() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null && { exec 3>&- 3<&-; return 0; } || return 1; }

# Never stomp something already listening — the user may have `make serve` or
# another `make admin-dev` running on purpose in a second terminal.
if port_busy "$API_PORT"; then
  die "port $API_PORT is already in use — the serving API (or something) is already up.
       Use 'make admin-dev' for just the GUI, or stop the other process first."
fi
if port_busy "$GUI_PORT"; then
  die "port $GUI_PORT is already in use — a dev GUI is already running.
       Stop it first (Ctrl+C in its terminal, or 'cd apps/admin && npx astro dev stop')."
fi

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
  # Only stops a GUI this script started (it holds the lock by then); a
  # pre-existing one was rejected above, so this never kills someone else's.
  ( cd apps/admin && "$astro_bin" dev stop >/dev/null 2>&1 )
  wait 2>/dev/null
  echo "[admin-stack] stopped."
}
trap cleanup INT TERM EXIT

# API in the background, in its own process group (uvicorn --reload spawns a
# reloader child; the negative-pid kill in cleanup reaps the whole group).
echo "[admin-stack] serving API -> http://localhost:${API_PORT}"
NEWS_COLLECTOR_PATH="$repo_root" setsid "$python_bin" -m news_collector.serving &
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
echo "[admin-stack] admin GUI -> http://localhost:${GUI_PORT}  (Ctrl+C stops both)"
( cd apps/admin && npm run dev ) || true

# Reached only if the GUI returned on its own. If Astro backgrounded it, keep
# the API alive and block on it instead of tearing the stack down.
if ( cd apps/admin && "$astro_bin" dev status 2>/dev/null | grep -qi "running" ); then
  echo "[admin-stack] GUI running in the background — Ctrl+C stops everything"
  wait "$api_pid"
fi
