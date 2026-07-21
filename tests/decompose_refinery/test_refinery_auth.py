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


# ---------------------------------------------------------------------------
# Page-boundary and source-order tests (Plan 018 — global auth gate)
# ---------------------------------------------------------------------------


def test_global_auth_gate_precedes_tab_construction():
    """The global auth gate must appear before st.tabs(...) in admin_panel.py."""
    source = ADMIN_PANEL.read_text(encoding="utf-8")
    tree = ast.parse(source)

    # Find the first call to st.tabs
    tabs_lineno: int | None = None
    auth_stop_lineno: int | None = None

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute) and node.func.attr == "tabs":
                tabs_lineno = node.lineno
            if (
                isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "st"
                and node.func.attr == "stop"
            ):
                # Only the first st.stop() inside the global auth gate matters
                if auth_stop_lineno is None:
                    auth_stop_lineno = node.lineno

    assert tabs_lineno is not None, "st.tabs(...) not found in admin_panel.py"
    assert auth_stop_lineno is not None, (
        "st.stop() inside global auth gate not found — "
        "unauthenticated execution would reach tab construction."
    )
    assert auth_stop_lineno < tabs_lineno, (
        f"st.stop() at line {auth_stop_lineno} must appear before "
        f"st.tabs(...) at line {tabs_lineno}."
    )


def test_secret_tokens_not_passed_to_text_input_widgets():
    """Password widgets must not receive existing token values."""
    source = ADMIN_PANEL.read_text(encoding="utf-8")
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not (
            isinstance(node.func, ast.Attribute) and node.func.attr == "text_input"
        ):
            continue
        kwargs = {kw.arg: kw for kw in node.keywords if kw.arg is not None}
        if kwargs.get("type") and isinstance(kwargs["type"].value, ast.Constant):
            if kwargs["type"].value.value != "password":
                continue
        # A password text_input that receives a reference to GITHUB_TOKEN
        # or REFINERY_UI_TOKEN via secrets.get(...) would violate the rule.
        if not node.args:
            continue
        first_arg = node.args[0]
        if isinstance(first_arg, ast.Call) and isinstance(
            first_arg.func, ast.Attribute
        ):
            if first_arg.func.attr == "get":
                arg_target = (
                    first_arg.func.value.id
                    if isinstance(first_arg.func.value, ast.Name)
                    else None
                )
                raise AssertionError(
                    f"Line {node.lineno}: text_input receives an existing secret "
                    f"value via {arg_target or 'unknown'}.get(...). "
                    "Render password inputs blank to avoid round-tripping secrets."
                )


def test_docker_compose_binds_refinery_to_loopback():
    """docker-compose.yml must bind the Refinery port to 127.0.0.1."""
    compose_path = Path(__file__).resolve().parents[2] / "docker-compose.yml"
    text = compose_path.read_text(encoding="utf-8")

    import yaml as _yaml

    parsed = _yaml.safe_load(text)
    refinery_ports = parsed.get("services", {}).get("refinery", {}).get("ports", [])
    assert refinery_ports, "Refinery service has no ports defined."

    bindings = [p for p in refinery_ports if isinstance(p, str) and "8501" in p]
    assert bindings, "No port 8501 binding found for Refinery."
    assert any(b.strip().startswith("127.0.0.1:") for b in bindings), (
        f"Refinery port 8501 must bind to loopback (127.0.0.1), " f"found: {bindings}"
    )
