"""
Entry point to run the Noticiencias HTTP serving layer.

Usage:
    python -m news_collector.serving
"""

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
RELOAD_EXCLUDES = [str(_REPO_ROOT / name) for name in ("temp", "data", "logs")]

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "news_collector.serving.__main__:app",
        host="0.0.0.0",  # noqa: S104 — intended for local dev server
        port=8000,
        reload=True,
        reload_excludes=RELOAD_EXCLUDES,
    )
