"""
tests/decompose_refinery/test_refinery_auth.py

Verifies the hardened token gate ``require_refinery_auth`` in
``apps/refinery/admin_panel.py`` (Plan 012 — constant-time compare + failed-attempt
logging).

``admin_panel.py`` is a top-level Streamlit script whose import executes the whole
UI (``st.tabs(...)`` unpacking, page config, config/secret loads), and Streamlit is
not installed in the test environment. Rather than stub the entire UI, this test
extracts only ``require_refinery_auth`` plus the two ``REFINERY_UI_*`` constants via
AST and executes them in a controlled namespace with a minimal fake ``st``, the real
``os``/``hmac`` modules, and a stub ``logger``. This keeps the surface small and
deterministic while still exercising the real comparison and logging code.
"""

from __future__ import annotations

import ast
import hmac
import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ADMIN_PANEL = (
    Path(__file__).resolve().parents[2] / "apps" / "refinery" / "admin_panel.py"
)

# Names we need to lift out of the script: the auth function and the env-var keys
# it reads. Everything else in the module is intentionally left unexecuted.
_WANTED_FUNCS = {"require_refinery_auth"}
_WANTED_CONSTS = {"REFINERY_UI_TOKEN_KEY", "REFINERY_UI_BYPASS_KEY"}


def _extract_auth_namespace(fake_st: object, logger: object) -> dict:
    """Return a namespace containing ``require_refinery_auth`` wired to the fakes.

    The function body is exec'd with ``st``, ``logger``, real ``os``, and real
    ``hmac`` bound so the actual constant-time comparison and warning call run.
    """

    source = ADMIN_PANEL.read_text(encoding="utf-8")
    tree = ast.parse(source)

    selected: list[ast.stmt] = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in _WANTED_FUNCS:
            selected.append(node)
        elif isinstance(node, ast.Assign):
            targets = {t.id for t in node.targets if isinstance(t, ast.Name)}
            if targets & _WANTED_CONSTS:
                selected.append(node)

    module = ast.Module(body=selected, type_ignores=[])
    ast.fix_missing_locations(module)

    namespace: dict = {
        "st": fake_st,
        "os": os,
        "hmac": hmac,
        "logger": logger,
    }
    exec(compile(module, str(ADMIN_PANEL), "exec"), namespace)  # noqa: S102
    return namespace


class _FakeExpander:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeStreamlit:
    """Minimal Streamlit stand-in for ``require_refinery_auth``."""

    def __init__(self, entered: str | None = None):
        self.session_state: dict = {}
        self._entered = entered
        self.warnings: list[str] = []
        self.errors: list[str] = []
        self.successes: list[str] = []

    def warning(self, msg: str) -> None:
        self.warnings.append(msg)

    def error(self, msg: str) -> None:
        self.errors.append(msg)

    def success(self, msg: str) -> None:
        self.successes.append(msg)

    def expander(self, *_args, **_kwargs):
        return _FakeExpander()

    def text_input(self, *_args, **_kwargs):
        return self._entered


@pytest.fixture
def logger() -> MagicMock:
    return MagicMock()


def _auth(fake_st: _FakeStreamlit, logger: MagicMock):
    ns = _extract_auth_namespace(fake_st, logger)
    return ns["require_refinery_auth"]


def test_bypass_env_returns_true(monkeypatch, logger):
    """REFINERY_UI_UNSAFE_ALLOW=1 short-circuits to True with a warning."""
    monkeypatch.setenv("REFINERY_UI_UNSAFE_ALLOW", "1")
    st = _FakeStreamlit()
    require_refinery_auth = _auth(st, logger)

    assert require_refinery_auth({}) is True
    assert st.warnings  # the bypass warning was surfaced
    logger.warning.assert_not_called()


def test_already_authenticated_returns_true_without_prompt(monkeypatch, logger):
    """A preset session flag returns True without prompting for a token."""
    monkeypatch.delenv("REFINERY_UI_UNSAFE_ALLOW", raising=False)
    st = _FakeStreamlit()
    st.session_state["refinery_ui_authenticated"] = True
    require_refinery_auth = _auth(st, logger)

    assert require_refinery_auth({"REFINERY_UI_TOKEN": "secret"}) is True
    logger.warning.assert_not_called()


def test_missing_token_returns_false(monkeypatch, logger):
    """No configured token => gate is closed with an error message."""
    monkeypatch.delenv("REFINERY_UI_UNSAFE_ALLOW", raising=False)
    monkeypatch.delenv("REFINERY_UI_TOKEN", raising=False)
    st = _FakeStreamlit()
    require_refinery_auth = _auth(st, logger)

    assert require_refinery_auth({}) is False
    assert st.errors


def test_wrong_token_returns_false_and_logs(monkeypatch, logger):
    """A wrong entered token returns False and logs an event (no secret value)."""
    monkeypatch.delenv("REFINERY_UI_UNSAFE_ALLOW", raising=False)
    st = _FakeStreamlit(entered="not-the-token")
    require_refinery_auth = _auth(st, logger)

    assert require_refinery_auth({"REFINERY_UI_TOKEN": "the-secret"}) is False
    logger.warning.assert_called_once_with("refinery.auth.failed")
    # The event must not leak the entered value or the token.
    logged = logger.warning.call_args.args[0]
    assert "not-the-token" not in logged
    assert "the-secret" not in logged


def test_correct_token_returns_true(monkeypatch, logger):
    """The correct token authenticates and sets the session flag."""
    monkeypatch.delenv("REFINERY_UI_UNSAFE_ALLOW", raising=False)
    st = _FakeStreamlit(entered="the-secret")
    require_refinery_auth = _auth(st, logger)

    assert require_refinery_auth({"REFINERY_UI_TOKEN": "the-secret"}) is True
    assert st.session_state.get("refinery_ui_authenticated") is True
    logger.warning.assert_not_called()
