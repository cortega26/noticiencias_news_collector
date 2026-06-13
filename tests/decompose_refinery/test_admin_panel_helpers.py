"""Pure-helper tests for the Streamlit admin panel.

``apps/refinery/admin_panel.py`` cannot be imported under the test venv because
Streamlit is not installed there. The two helpers exercised here (``_index_of``
for source-editor preselection and ``_as_float`` for null-safe score component
rendering) are closure-free, so we extract their ``FunctionDef`` nodes from the
module AST and ``exec`` them in an isolated namespace.
"""

from __future__ import annotations

import ast
from pathlib import Path

ADMIN_PANEL = (
    Path(__file__).resolve().parents[2] / "apps" / "refinery" / "admin_panel.py"
)


def _load_helper(name: str):
    """Return the named top-level-or-nested function defined in admin_panel.py."""
    tree = ast.parse(ADMIN_PANEL.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            module = ast.Module(body=[node], type_ignores=[])
            namespace: dict = {}
            exec(compile(module, str(ADMIN_PANEL), "exec"), namespace)  # noqa: S102
            return namespace[name]
    raise AssertionError(f"helper {name!r} not found in {ADMIN_PANEL}")


# ---------------------------------------------------------------------------
# _index_of — source-editor selectbox preselection
# ---------------------------------------------------------------------------


def test_index_of_finds_existing_value():
    index_of = _load_helper("_index_of")
    assert index_of(["a", "b", "c"], "b") == 1


def test_index_of_missing_value_returns_default():
    index_of = _load_helper("_index_of")
    assert index_of(["a"], "zzz") == 0


def test_index_of_none_value_returns_default():
    index_of = _load_helper("_index_of")
    assert index_of(["a", "b"], None) == 0


def test_index_of_custom_default():
    index_of = _load_helper("_index_of")
    assert index_of(["a", "b"], "missing", default=1) == 1


# ---------------------------------------------------------------------------
# _as_float — null-safe score component conversion
# ---------------------------------------------------------------------------


def test_as_float_none_returns_default():
    as_float = _load_helper("_as_float")
    assert as_float(None) == 0.0


def test_as_float_numeric_string():
    as_float = _load_helper("_as_float")
    assert as_float("1.5") == 1.5


def test_as_float_invalid_string_returns_default():
    as_float = _load_helper("_as_float")
    assert as_float("x") == 0.0


def test_as_float_passthrough_number():
    as_float = _load_helper("_as_float")
    assert as_float(0.0) == 0.0
    assert as_float(2) == 2.0
