"""Reload-exclude guard for the serving dev entrypoint (plan 062).

`make serve` / `make admin` run uvicorn with `--reload` rooted at the repo.
Publication runs clone whole repos under `temp/` and collection runs rewrite
`data/`/`logs/` — if the watcher sees those writes it restarts the server
mid-run and kills the in-process background run (run 15 died 6s after
starting on its own `temp/source` clone).

Entries must be ABSOLUTE directories: uvicorn matches `reload_excludes`
with right-anchored `Path.match` (relative globs like `temp/*` never match
nested files) and compares `exclude_dirs` against absolute `path.parents`
(relative dirs never equal them).
"""

from pathlib import Path

from news_collector.serving.__main__ import RELOAD_EXCLUDES


def _watch_filter():  # type: ignore[no-untyped-def]
    from types import SimpleNamespace

    from uvicorn.supervisors.watchfilesreload import FileFilter

    return FileFilter(
        SimpleNamespace(reload_excludes=list(RELOAD_EXCLUDES), reload_includes=[])
    )


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent.parent


def test_reload_excludes_cover_runtime_write_dirs() -> None:
    assert {Path(entry).name for entry in RELOAD_EXCLUDES} >= {
        "temp",
        "data",
        "logs",
    }
    root = _repo_root()
    for entry in RELOAD_EXCLUDES:
        assert Path(entry).is_absolute(), entry
        assert Path(entry).parent == root, entry


def test_reload_filter_ignores_run_artifacts_but_watches_sources() -> None:
    watch = _watch_filter()
    root = _repo_root()
    ignored = [
        root / "temp" / "source" / "news_collector" / "x.py",
        root / "temp" / "target" / "deep" / "nested" / "y.py",
        root / "data" / "news_v3.db",
        root / "logs" / "api.log",
    ]
    watched = [
        root / "news_collector" / "serving" / "api.py",
        root / "scripts" / "run_collector.py",
    ]
    assert all(not watch(path) for path in ignored)
    assert all(watch(path) for path in watched)
