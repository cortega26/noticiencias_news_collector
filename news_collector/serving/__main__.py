"""
Entry point to run the Noticiencias HTTP serving layer.

Usage:
    python -m news_collector.serving

Env:
    SERVING_PORT    TCP port to bind (default: 8000). Honored strictly: an
                    invalid value fails closed, and a busy port surfaces
                    uvicorn's bind error. Port *selection* (next-free fallback)
                    belongs to the caller — see scripts/dev/admin_stack.sh.
    SERVING_RELOAD  uvicorn auto-reload (default: 1). Set to 0/false/no/off
                    for publication sessions: a run executes in-process for
                    ~12 min and any watched source edit would restart the
                    server and kill it mid-flight (runs 58/60). Invalid
                    values fail closed, same convention as SERVING_PORT.
"""

import os
from pathlib import Path

from news_collector.serving.api import create_app

app = create_app()

# Directories written at runtime that must never trigger a `--reload`
# restart. Publication runs clone whole repos under `temp/` and collection
# runs rewrite `data/`/`logs/` — without these excludes the reloader
# restarts the server mid-run and kills the in-process background run
# (plan 062: run 15 died 6s after starting on its own `temp/source` clone).
#
# Entries MUST be absolute directory paths: uvicorn matches `reload_excludes`
# with right-anchored `Path.match` (relative globs like `temp/*` never match
# nested files) and compares `exclude_dirs` against absolute `path.parents`
# (relative dirs never equal them). Anchored at the file location so this
# holds regardless of the process working directory.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
# The uvicorn watcher only honors ABSOLUTE EXISTING directories as
# exclude_dirs (checked via `is_dir` at startup) — so make sure the
# runtime workspace exists here, not just when the first run needs it.
# Without this, a fresh checkout/container (no temp/ yet) silently loses
# the exclusion and the first publication run kills the server again.
for _runtime_dir in ("temp", "data", "logs"):
    (_REPO_ROOT / _runtime_dir).mkdir(parents=True, exist_ok=True)
RELOAD_EXCLUDES = [str(_REPO_ROOT / name) for name in ("temp", "data", "logs")]


DEFAULT_PORT = 8000

_FALSE_VALUES = frozenset({"0", "false", "no", "off"})
_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})


def _resolve_port() -> int:
    """Resolve the bind port from SERVING_PORT, failing closed on garbage."""
    raw = os.environ.get("SERVING_PORT", str(DEFAULT_PORT)).strip()
    try:
        port = int(raw)
    except ValueError:
        raise SystemExit(
            f"news_collector.serving: invalid SERVING_PORT={raw!r} (must be an integer 1-65535)"
        ) from None
    if not 1 <= port <= 65535:
        raise SystemExit(
            f"news_collector.serving: invalid SERVING_PORT={raw!r} (must be an integer 1-65535)"
        )
    return port


def _resolve_reload() -> bool:
    """Resolve uvicorn auto-reload from SERVING_RELOAD, failing closed.

    Defaults to True (normal development). Publication runs execute as
    daemon threads inside this process; with reload on, any watched source
    change restarts the worker and kills the run (runs 58/60). Operators
    publishing from the desk run the stack with `SERVING_RELOAD=0`.
    """
    raw = os.environ.get("SERVING_RELOAD", "1").strip().lower()
    if raw in _FALSE_VALUES:
        return False
    if raw in _TRUE_VALUES:
        return True
    raise SystemExit(
        f"news_collector.serving: invalid SERVING_RELOAD={raw!r} "
        "(expected one of: 1/0, true/false, yes/no, on/off)"
    )


def main() -> None:
    """Launch the dev server (auto-reload by default, runtime dirs excluded)."""
    import uvicorn

    uvicorn.run(
        "news_collector.serving.__main__:app",
        host="0.0.0.0",  # noqa: S104 # nosec B104 — local dev server only
        port=_resolve_port(),
        reload=_resolve_reload(),
        reload_excludes=RELOAD_EXCLUDES,
    )


if __name__ == "__main__":  # pragma: no cover - process entrypoint
    main()
