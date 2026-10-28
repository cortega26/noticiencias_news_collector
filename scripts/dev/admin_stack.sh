#!/usr/bin/env bash
#
# Run the full Refinery admin stack for local development:
#   - serving API  (FastAPI, uvicorn; --reload on by default, :8000)
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
#   SERVING_RELOAD    uvicorn auto-reload for the API (default: 1). Set to
#                     0/false/no/off for publication sessions: a run lives
#                     ~12 min inside this process and any watched source edit
#                     restarts the API and kills it (runs 58/60).
#   ADMIN_STACK_MODE  qué hacer si ya hay un stack del admin (plan 204):
#                       reuse   (por defecto) si está sano, muestra sus URLs y sale;
#                       restart lo reemplaza por uno nuevo con el código actual;
#                       heal    repara restos rotos y sale sin arrancar nada;
#                       status  solo diagnostica (sale 1 si encuentra algo roto).
#                     Los restos rotos (GUI sin API, API huérfana) se reparan
#                     siempre en reuse/restart. Eventos en .cache/admin-stack/events.log.
#   WEBHOOK_INBOX_PULL  best-effort pull of pending frontend callback receipts
#                     from the hosted inbox into this local DB before starting
#                     (default: 0). Needs BACKEND_ADMIN_URL (or
#                     BACKEND_WEBHOOK_URL) + ADMIN_API_KEY; see ADR-0011 and
#                     `make webhooks-pull`.
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
# Rutas relativas a apps/admin. Se pueden sustituir en los tests.
astro_bin="${ADMIN_ASTRO_BIN:-node_modules/.bin/astro}"
# Marca que llevan las API arrancadas por este script; solo esas se detienen.
owner_id="${ADMIN_STACK_OWNER_ID:-$repo_root}"
state_dir="${ADMIN_STACK_STATE_DIR:-$repo_root/.cache/admin-stack}"
events_log="$state_dir/events.log"

API_PORT_DEFAULT=8000
GUI_PORT_DEFAULT=4321
PORT_SCAN_RANGE=100

if [[ -n "${API_PORT+x}" ]]; then API_EXPLICIT=1; else API_PORT=$API_PORT_DEFAULT; API_EXPLICIT=0; fi
if [[ -n "${GUI_PORT+x}" ]]; then GUI_EXPLICIT=1; else GUI_PORT=$GUI_PORT_DEFAULT; GUI_EXPLICIT=0; fi

die() { echo "admin-stack: $*" >&2; exit 1; }

ADMIN_STACK_MODE="${ADMIN_STACK_MODE:-reuse}"
case "$ADMIN_STACK_MODE" in
  reuse|restart|heal|status) ;;
  *) die "ADMIN_STACK_MODE='$ADMIN_STACK_MODE' debe ser reuse, restart, heal o status" ;;
esac

if [[ "$ADMIN_STACK_MODE" == reuse || "$ADMIN_STACK_MODE" == restart ]]; then
  [[ -x "$python_bin" ]] || die "python interpreter not found at '$python_bin' — run 'make bootstrap' first"
  bash scripts/dev/check_admin_dependencies.sh
fi

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

# --- Autorreparación: detectar un stack del admin que ya esté corriendo ----
#
# Astro solo admite un `astro dev` por proyecto (archivo de bloqueo). Antes,
# un segundo `make admin` arrancaba una API duplicada, fallaba al levantar la
# GUI y aun así anunciaba éxito. Ahora se revisa primero qué está corriendo.
# Solo se detienen las API marcadas con nuestro ADMIN_STACK_OWNER y la GUI
# que tiene el bloqueo de este proyecto; un `make serve` en otra terminal no
# se toca nunca.

# Autoaprendizaje: cada acción correctiva queda registrada para que un
# problema recurrente se vea en vez de repararse en silencio para siempre.
record_event() {
  mkdir -p "$state_dir" 2>/dev/null || return 0
  printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >>"$events_log" 2>/dev/null || true
}

report_recurring_heals() {
  [[ -f "$events_log" ]] || return 0
  local since count
  since=$(date -u -d '7 days ago' +%Y-%m-%dT%H:%M:%SZ 2>/dev/null) || return 0
  count=$(awk -v s="$since" '$1 >= s && $2 ~ /^(healed|gui_failed)$/' "$events_log" | wc -l)
  if (( count >= 3 )); then
    echo "[admin-stack] AVISO: $count reparaciones o fallos en los últimos 7 días; revisa $events_log para encontrar la causa de fondo." >&2
  fi
}

http_ok() { curl -fsS -o /dev/null -m 3 "$1" 2>/dev/null; }

proc_env() { tr '\0' '\n' <"/proc/$1/environ" 2>/dev/null | sed -n "s/^$2=//p" | head -n1; }

# Imprime "pid puerto" del servidor Astro de este proyecto, si hay uno.
astro_lock_holder() {
  local out pid port
  out=$( cd apps/admin && "$astro_bin" dev status 2>/dev/null ) || return 1
  pid=$(sed -n 's/.*(pid \([0-9]\+\).*/\1/p' <<<"$out")
  port=$(sed -n 's/.*localhost:\([0-9]\+\).*/\1/p' <<<"$out")
  [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null || return 1
  echo "$pid ${port:-?}"
}

stop_existing_gui() {
  ( cd apps/admin && "$astro_bin" dev stop >/dev/null 2>&1 ) || true
  # `astro dev stop` puede volver antes de liberar el bloqueo.
  for _ in $(seq 1 20); do
    astro_lock_holder >/dev/null || return 0
    sleep 0.5
  done
  echo "[admin-stack] AVISO: la GUI anterior sigue con el bloqueo tras 10 s." >&2
}

# Imprime los PID de las API que este script arrancó (marca del dueño).
owned_api_pids() {
  local pid
  for pid in $(pgrep -f -- '-m news_collector.serving' 2>/dev/null); do
    [[ "$(proc_env "$pid" ADMIN_STACK_OWNER)" == "$owner_id" ]] && echo "$pid"
  done
  return 0
}

stop_pgroup() {
  local pgid
  pgid=$(ps -o pgid= -p "$1" 2>/dev/null | tr -d ' ') || return 0
  [[ -n "$pgid" ]] || return 0
  kill -TERM "-$pgid" 2>/dev/null || true
  for _ in 1 2 3 4 5 6; do kill -0 "-$pgid" 2>/dev/null || return 0; sleep 1; done
  kill -KILL "-$pgid" 2>/dev/null || true
}

diagnose_existing_stack() {
  local holder gui_pid gui_port target pids pid broken=0
  report_recurring_heals
  if holder=$(astro_lock_holder); then
    read -r gui_pid gui_port <<<"$holder"
    target=$(proc_env "$gui_pid" ADMIN_API_TARGET)
    target="${target:-http://localhost:8000}"
    if http_ok "http://localhost:${gui_port}/" && http_ok "${target%/}/healthz"; then
      echo "[admin-stack] ya hay un stack del admin corriendo y sano:"
      echo "[admin-stack]   GUI : http://localhost:${gui_port}  (pid $gui_pid)"
      echo "[admin-stack]   API : ${target}"
      if grep -q 'noticiencias-admin\.service' "/proc/$gui_pid/cgroup" 2>/dev/null; then
        echo "[admin-stack]   (es el servicio systemd del plan 203; para cargar código nuevo: systemctl --user restart noticiencias-admin)"
      fi
      case "$ADMIN_STACK_MODE" in
        status|heal) exit 0 ;;
        reuse)
          record_event "reused gui=$gui_port api=$target"
          echo "[admin-stack] se reutiliza (ADMIN_STACK_MODE=restart lo reemplaza con el código actual)."
          exit 0 ;;
        restart)
          echo "[admin-stack] reiniciando, como se pidió…"
          stop_existing_gui
          for pid in $(owned_api_pids); do
            [[ "$target" == *":$(proc_env "$pid" SERVING_PORT)"* ]] && stop_pgroup "$pid"
          done
          record_event "restarted gui=$gui_port api=$target" ;;
      esac
    else
      broken=1
      echo "[admin-stack] stack roto: la GUI (pid $gui_pid, :$gui_port) está viva pero su API ${target} no responde." >&2
      if [[ "$ADMIN_STACK_MODE" != status ]]; then
        echo "[admin-stack] reparando: se detiene esa GUI." >&2
        stop_existing_gui
        record_event "healed stale_gui gui=$gui_port api=$target"
      fi
    fi
  fi
  # Las API que arrancamos antes y ya no tienen GUI son huérfanas: liberar puertos.
  if ! astro_lock_holder >/dev/null; then
    pids=$(owned_api_pids)
    if [[ -n "$pids" ]]; then
      broken=1
      echo "[admin-stack] API huérfana(s) de una ejecución anterior: $(echo $pids)" >&2
      if [[ "$ADMIN_STACK_MODE" != status ]]; then
        echo "[admin-stack] reparando: se detienen." >&2
        for pid in $pids; do stop_pgroup "$pid"; done
        record_event "healed orphan_api pids=$(echo $pids)"
      fi
    fi
  fi
  case "$ADMIN_STACK_MODE" in
    status)
      (( broken )) && exit 1
      echo "[admin-stack] no hay ningún stack del admin corriendo."
      exit 0 ;;
    heal)
      (( broken )) || echo "[admin-stack] nada que reparar."
      exit 0 ;;
  esac
}

diagnose_existing_stack

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

# ADR-0011: the hosted serving instance is only a durable inbox for frontend
# callbacks; replay pending deliveries into this local DB before starting the
# stack so the admin shows truthful publication state. Opt-in and best-effort.
case "${WEBHOOK_INBOX_PULL:-0}" in
  1|true|yes|on)
    echo "[admin-stack] pulling pending webhook receipts (ADR-0011)…"
    timeout 30 "$python_bin" scripts/ops/pull_webhook_receipts.py \
      || echo "[admin-stack] WARNING: webhook pull failed — continuing; retry with 'make webhooks-pull'." >&2
    ;;
esac

api_pid=""
gui_port_owned=""
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
  # Solo se detiene una GUI que arrancó este script: `astro dev stop` apunta
  # a quien tenga el bloqueo del proyecto, que puede ser el stack de otra terminal.
  local holder
  if [[ -n "$gui_port_owned" ]] && holder=$(astro_lock_holder) && [[ "${holder#* }" == "$gui_port_owned" ]]; then
    ( cd apps/admin && "$astro_bin" dev stop >/dev/null 2>&1 )
  fi
  wait 2>/dev/null
  echo "[admin-stack] stopped."
}
# Las señales deben terminar el script; si no, tras Ctrl+C seguiría ejecutando
# la comprobación de la GUI y registraría un fallo falso.
trap 'cleanup; exit 130' INT
trap 'cleanup; exit 143' TERM
trap cleanup EXIT

# API in the background, in its own process group (uvicorn --reload spawns a
# reloader child; the negative-pid kill in cleanup reaps the whole group).
echo "[admin-stack] starting serving API on :${API_PORT} ..."
ADMIN_STACK_OWNER="$owner_id" SERVING_PORT="$API_PORT" NEWS_COLLECTOR_PATH="$repo_root" setsid "$python_bin" -m news_collector.serving &
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
gui_port_owned="$GUI_PORT"
gui_rc=0
( cd apps/admin && npm run dev -- --port "$GUI_PORT" ) || gui_rc=$?

# Se llega aquí solo si la GUI volvió por su cuenta. Autocorrección: solo
# vale un servidor Astro que atienda *nuestro* puerto; otra cosa es un fallo.
if holder=$(astro_lock_holder) && [[ "${holder#* }" == "$GUI_PORT" ]]; then
  echo "[admin-stack] GUI running in the background — Ctrl+C stops everything"
  wait "$api_pid"
else
  gui_port_owned=""
  record_event "gui_failed port=$GUI_PORT rc=$gui_rc"
  die "la GUI del admin no arrancó en :$GUI_PORT (código $gui_rc; revisa la salida de arriba). Se detiene la API. Diagnostica con 'ADMIN_STACK_MODE=status make admin'."
fi
