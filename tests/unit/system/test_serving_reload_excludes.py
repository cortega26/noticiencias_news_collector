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

import pytest

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


def test_main_invokes_uvicorn_with_configured_excludes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The dev entrypoint passes the same excludes to uvicorn (covers the
    `main()` launcher so the coverage ratchet holds on `__main__.py`)."""
    import uvicorn

    from news_collector.serving.__main__ import RELOAD_EXCLUDES, main

    calls: dict[str, object] = {}

    def _fake_run(*args: object, **kwargs: object) -> None:
        calls["args"] = args
        calls["kwargs"] = kwargs

    monkeypatch.setattr(uvicorn, "run", _fake_run)
    main()
    assert calls["args"] == ("news_collector.serving.__main__:app",)
    kwargs = calls["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["port"] == 8000
    assert kwargs["reload"] is True
    assert kwargs["reload_excludes"] == RELOAD_EXCLUDES


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
