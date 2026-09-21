"""Unit tests for the serving entrypoint port resolution.

`_resolve_port()` is the only logic in `news_collector/serving/__main__.py`
that is safe to execute without binding a socket: `main()` itself launches
uvicorn and is covered by the live `make admin` / `make serve` smoke path.
"""

import importlib
import os
from unittest.mock import patch

import pytest

import news_collector.serving.__main__ as serving_main


@pytest.fixture(autouse=True)
def _clean_serving_port_env(monkeypatch):
    monkeypatch.delenv("SERVING_PORT", raising=False)


def test_resolve_port_defaults_to_8000():
    assert serving_main._resolve_port() == 8000


def test_resolve_port_honors_serving_port_env(monkeypatch):
    monkeypatch.setenv("SERVING_PORT", "9000")
    assert serving_main._resolve_port() == 9000


def test_resolve_port_strips_whitespace(monkeypatch):
    monkeypatch.setenv("SERVING_PORT", "  8001  ")
    assert serving_main._resolve_port() == 8001


@pytest.mark.parametrize("raw", ["abc", "", "80.5", "8k", "-1"])
def test_resolve_port_rejects_non_integers(raw, monkeypatch):
    monkeypatch.setenv("SERVING_PORT", raw)
    with pytest.raises(SystemExit, match="invalid SERVING_PORT"):
        serving_main._resolve_port()


@pytest.mark.parametrize("raw", ["0", "65536", "99999"])
def test_resolve_port_rejects_out_of_range(raw, monkeypatch):
    monkeypatch.setenv("SERVING_PORT", raw)
    with pytest.raises(SystemExit, match="invalid SERVING_PORT"):
        serving_main._resolve_port()


def test_main_passes_resolved_port_to_uvicorn(monkeypatch):
    """`main()` must propagate SERVING_PORT instead of a hardcoded 8000."""
    import uvicorn

    monkeypatch.setenv("SERVING_PORT", "8001")
    with patch.object(uvicorn, "run") as run_mock:
        serving_main.main()
    _, kwargs = run_mock.call_args
    assert kwargs["port"] == 8001


def test_reload_imports_cleanly():
    """Module reload must not re-execute side effects beyond dir creation."""
    reloaded = importlib.reload(serving_main)
    assert reloaded._resolve_port() == 8000
