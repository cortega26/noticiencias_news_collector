"""Tests for admin_panel._balance_scoring_weights().

Regression for the scoring-weights save bug: editing one weight slider
(e.g. recency 0.10 -> 0.30) left the sum of the four weights away from 1.0,
which config_settings.validate_config() rejects, so save_toml_config()
silently no-oped and config.toml kept the old weights.

``apps/refinery/admin_panel.py`` cannot be imported under the test venv
(Streamlit isn't installed there). _balance_scoring_weights has no Streamlit
dependency; its FunctionDef plus the SCORING_WEIGHT_KEYS constant are
extracted via AST and exec'd, mirroring the pattern in
tests/unit/refinery/test_save_toml_config.py.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, Dict

ADMIN_PANEL = (
    Path(__file__).resolve().parents[3] / "apps" / "refinery" / "admin_panel.py"
)


def _load_balance_scoring_weights():
    tree = ast.parse(ADMIN_PANEL.read_text(encoding="utf-8"))
    constant_node = None
    func_node = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            if node.targets[0].id == "SCORING_WEIGHT_KEYS":
                constant_node = node
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == "SCORING_WEIGHT_KEYS":
                constant_node = node
        if (
            isinstance(node, ast.FunctionDef)
            and node.name == "_balance_scoring_weights"
        ):
            func_node = node

    assert constant_node is not None, "SCORING_WEIGHT_KEYS not found"
    assert func_node is not None, "_balance_scoring_weights not found"

    module = ast.Module(body=[constant_node, func_node], type_ignores=[])
    namespace: Dict[str, Any] = {"Any": Any, "Dict": Dict}
    exec(compile(module, str(ADMIN_PANEL), "exec"), namespace)  # noqa: S102
    return namespace["_balance_scoring_weights"], namespace["SCORING_WEIGHT_KEYS"]


def _weights_sum(balanced: Dict[str, float], keys) -> float:
    return round(sum(balanced[k] for k in keys), 4)


def test_moved_weight_value_is_preserved():
    balance, keys = _load_balance_scoring_weights()
    previous = {
        "source_credibility": 0.2,
        "recency": 0.2,
        "content_quality": 0.3,
        "engagement_potential": 0.3,
    }

    result = balance(previous, "recency", 0.30)

    assert result["recency"] == 0.30
    assert _weights_sum(result, keys) == 1.0


def test_others_scale_proportionally_from_previous():
    balance, keys = _load_balance_scoring_weights()
    previous = {
        "source_credibility": 0.1,
        "recency": 0.3,
        "content_quality": 0.3,
        "engagement_potential": 0.3,
    }

    result = balance(previous, "recency", 0.5)

    # Remaining 0.5 split among the untouched three in their previous ratio
    # (their previous total is 0.7, so scale = 0.5 / 0.7).
    assert result["recency"] == 0.5
    assert _weights_sum(result, keys) == 1.0
    assert result["source_credibility"] == round(0.1 * (0.5 / 0.7), 4)
    assert result["content_quality"] == round(0.3 * (0.5 / 0.7), 4)
    assert result["engagement_potential"] == round(0.3 * (0.5 / 0.7), 4)


def test_default_baseline_when_previous_missing_keys():
    balance, keys = _load_balance_scoring_weights()

    result = balance({}, "recency", 0.4)

    assert result["recency"] == 0.4
    assert _weights_sum(result, keys) == 1.0


def test_keep_clamped_to_one():
    balance, keys = _load_balance_scoring_weights()
    previous = {
        "source_credibility": 0.2,
        "recency": 0.2,
        "content_quality": 0.3,
        "engagement_potential": 0.3,
    }

    result = balance(previous, "recency", 1.0)

    assert result["recency"] == 1.0
    assert result["source_credibility"] == 0.0
    assert result["content_quality"] == 0.0
    assert result["engagement_potential"] == 0.0
    assert _weights_sum(result, keys) == 1.0


def test_keep_clamped_to_bottom():
    balance, keys = _load_balance_scoring_weights()
    previous = {
        "source_credibility": 0.2,
        "recency": 0.2,
        "content_quality": 0.3,
        "engagement_potential": 0.3,
    }

    result = balance(previous, "recency", -0.5)

    assert result["recency"] == 0.0
    assert _weights_sum(result, keys) == 1.0


def test_unknown_key_raises_value_error():
    balance, _ = _load_balance_scoring_weights()

    try:
        balance({"recency": 0.25}, "not_a_weight", 0.25)
    except ValueError:
        return
    raise AssertionError("expected ValueError for unknown weight key")


def test_result_satisfies_validate_config():
    """The balanced output must pass config_settings.validate_config()."""
    from noticiencias.config_manager import Config, load_config

    from news_collector.config.settings import validate_config

    balance, _ = _load_balance_scoring_weights()
    previous = {
        "source_credibility": 0.2,
        "recency": 0.2,
        "content_quality": 0.3,
        "engagement_potential": 0.3,
    }
    result = balance(previous, "recency", 0.30)

    payload = load_config().model_dump(mode="python")
    payload["scoring"]["weights"] = result

    # Cross-field validation invoked (sum-to-1.0 business rule) is exercised
    # explicitly; no assertion needed since it raises if unbalanced.
    validate_config(Config.model_validate(payload))
