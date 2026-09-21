# Spec — Admin stack resilient ports (`make admin` / `serve` / `admin-dev`)

Scope: `scripts/dev/admin_stack.sh`, `news_collector/serving/__main__.py`,
`Makefile` (serve/admin-dev/admin), `docs/RUNBOOK_LOCAL_DEV.md`.

## Problem

`make admin` died when the default API port was taken — the common case of a
leftover `make serve` in another terminal:

```
admin-stack: port 8000 is already in use — the serving API (or something) is already up.
make: *** [Makefile:135: admin] Error 1
```

## Behavior

1. **Defaults auto-bump.** Preferred API `8000` / GUI `4321` busy → next free
   port (scan capped at +100), with a loud `NOTE:` line. The GUI proxy
   (`ADMIN_API_TARGET`) follows the chosen API port automatically.
2. **Explicit pins are strict.** Exported `API_PORT=`/`GUI_PORT=` busy →
   die with a clear message (operator intent honored, no silent relocation).
3. **No collisions.** Overlapping selections (e.g. `API_PORT=4321`) bump the
   non-explicit side; two explicitly equal ports die as unsatisfiable.
4. **SERVING_PORT plumbing.** `news_collector.serving` binds `SERVING_PORT`
   (default 8000), failing closed on non-integer/out-of-range values.
   Precedence in `make serve`: `SERVING_PORT` > `API_PORT` > `8000`.
5. **Teardown unchanged.** One Ctrl+C stops both; a pre-existing occupant
   (e.g. the squatter on :8000) is never touched.

## Verification (real-run evidence, 2026-09-21)

- `:8000` occupied by a live serving API → `make admin` came up on
  **API :8001 + GUI :4321**, proxy `-> :8001`; `/healthz`, GUI `/`, and
  proxied `/v1/admin/analytics` all 200 (proxied hit confirmed in the
  :8001 uvicorn access log). Teardown freed both; :8000 untouched.
- `SERVING_PORT=abc` → `SystemExit` message, exit 1.
- `make lint` green; `tests/test_serving_admin_api.py` +
  `tests/unit/serving/` — 101 passed.
