"""Deterministic Promptfoo assertion for the offline editorial replay pilot.

Plan 080 Phase 3, development-only tooling. The evaluator applies the public
generated-article guardrail validator plus narrow, case-sensitive literal
expectations recorded in ``context["vars"]``. It does not call a model, the
network, or any production service.

Only expected content-validation failures become failed assertions. Any other
exception propagates so an evaluator bug cannot masquerade as a content defect.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

# Enable the repository's existing test isolation before importing project code:
# log files and the enrichment-metrics SQLite store are redirected to test paths.
os.environ["NEWS_COLLECTOR_TEST_MODE"] = "1"
os.environ["RUN_ENVIRONMENT"] = "test"

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from news_collector.components.editorial.ai_editor import (  # noqa: E402
    GeneratedArticleValidationError,
    validate_generated_article_markdown,
)


def _context_vars(context: Any) -> Mapping[str, Any]:
    if not isinstance(context, Mapping):
        raise TypeError("promptfoo assertion context must be a mapping")
    vars_ = context.get("vars")
    if not isinstance(vars_, Mapping):
        raise TypeError("promptfoo assertion context['vars'] must be a mapping")
    return vars_


def _string_list(vars_: Mapping[str, Any], key: str) -> list[str]:
    value = vars_.get(key)
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise TypeError(f"context['vars']['{key}'] must be a list of strings")
    return value


def _result(passed: bool, reason: str) -> dict[str, Any]:
    return {"pass": passed, "score": 1.0 if passed else 0.0, "reason": reason}


def get_assert(output: Any, context: Any) -> dict[str, Any]:
    """Return a binary GradingResult for one captured editorial output."""
    if not isinstance(output, str):
        raise TypeError("promptfoo output must be a string")

    vars_ = _context_vars(context)
    case_id = vars_.get("case_id")
    if not isinstance(case_id, str) or case_id == "":
        raise TypeError("context['vars']['case_id'] must be a nonempty string")

    stored_error = vars_.get("stored_error")
    if stored_error is not None and not isinstance(stored_error, str):
        raise TypeError("context['vars']['stored_error'] must be a string")
    if stored_error:
        return _result(
            False,
            f"{case_id}: captured provider error; content was not evaluated: "
            f"{stored_error}",
        )

    required = _string_list(vars_, "required_substrings")
    forbidden = _string_list(vars_, "forbidden_substrings")

    try:
        validate_generated_article_markdown(output)
    except GeneratedArticleValidationError as exc:
        code = getattr(exc, "error_code", "unknown")
        return _result(
            False,
            f"{case_id}: content validation failed [{code}]: {exc}",
        )

    missing = [literal for literal in required if literal not in output]
    if missing:
        return _result(
            False,
            f"{case_id}: missing required literal substring(s): {missing!r}",
        )

    present = [literal for literal in forbidden if literal in output]
    if present:
        return _result(
            False,
            f"{case_id}: forbidden literal substring(s) present: {present!r}",
        )

    return _result(
        True,
        f"{case_id}: content validation passed; required literals present; "
        "no forbidden literals",
    )
