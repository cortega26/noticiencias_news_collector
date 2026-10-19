# Spec — SERVING_RELOAD switch for publication-safe admin sessions

## Problem

`make admin` runs the serving API with `uvicorn --reload` hardcoded. A
publication run executes as a daemon thread inside that process and takes
~12 min (typical 733 s); any watched `.py` change (edit, merge, `git pull`)
restarts the worker and kills the run mid-flight. Runs 58 and 60 were both
lost this way, each leaving a stale `running` row that blocks single-flight
until the 1-hour lease expires. Content self-healing cannot help: the
process dies before any handler runs.

## Goal

Let an operator run the admin stack without auto-reload for publication
sessions, with zero behavior change by default:

1. `SERVING_RELOAD` env var parsed in `news_collector/serving/__main__.py`:
   unset/empty → `True` (today's behavior); `0/false/no/off` → `False`;
   `1/true/yes/on` → `True`; anything else fails closed with a clear
   `SystemExit` (same convention as `SERVING_PORT`).
2. `uvicorn.run(..., reload=_resolve_reload(), reload_excludes=...)` —
   excludes stay wired (harmless when reload is off).
3. `admin_stack.sh` inherits the env automatically (no code change needed);
   its header documents the switch. `docs/RUNBOOK_LOCAL_DEV.md` gets a
   one-line note.
4. Tests mirror `_resolve_port`'s matrix: default, truthy/falsy values,
   garbage rejection, and `main()` propagating the flag to uvicorn.

Non-goals: changing the default (auto-reload remains the dev default),
subprocess-per-run architecture, shortening the lease, admin GUI changes.

## Files

- `news_collector/serving/__main__.py`
- `scripts/dev/admin_stack.sh` (header docs only)
- `docs/RUNBOOK_LOCAL_DEV.md` (one note)
- `tests/unit/serving/test_main_port.py`

## Acceptance

- `SERVING_RELOAD=0 make admin` starts the API with reload disabled
  (verified by unit test on `main()`; live smoke = one publication run
  survives a source edit).
- Defaults unchanged when the var is unset.
- Invalid values fail closed.

## Verification

- `.venv/bin/python -m pytest tests/unit/serving/test_main_port.py -q --no-cov`
- `make lint`
- Manual: restart `make admin` with `SERVING_RELOAD=0` and confirm the API
  does not restart when a watched file is touched (`touch` a `.py`).
