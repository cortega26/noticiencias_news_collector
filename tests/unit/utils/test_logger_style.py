"""
Regression guard: loguru call sites must not use %-style formatting.

loguru formats braces ("{}"), not %-style ("%s"). A site written in the
Python-logging style with a literal "%s"/"%d"/"%r"/"%.Ns" placeholder renders
the placeholder verbatim and silently drops its arguments, losing signal from
info/error/warning calls.

This test scans every loguru-managed module and fails whenever a logger call's
first message literal still contains a %-style placeholder.

Exemptions (each verified correct, documented):
- Modules built on :mod:`logging` (stdlib): %-style formats natively, before any
  forwarding to loguru. Detected via ``import logging`` + ``logging.getLogger``.
- Pre-formatted ``"...%s..." % (tuple)`` expressions: the string is fully built
  by the modulo operator before loguru ever sees it.

When adding a NEW logger call, use braces and pass values as arguments:
``logger.info("article {} saved", article_id)``. Never ``"%s"``.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path
from typing import List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[3]
SCAN_ROOTS = ("news_collector", "apps/refinery", "scripts")
EXCLUDE_DIR_PARTS = {".venv", "__pycache__", ".git", "node_modules"}

# logger.<level>( <message> ... ) — multi-line aware
_CALL_RE = re.compile(
    r"logger\.(?:info|warning|error|debug|exception|success|critical)\s*\((.*?)\)\s*$",
    re.MULTILINE | re.DOTALL,
)
# a `%`-style placeholder inside a string literal (supports %.Ns, %s, %d, %r, %f...)
_PLACEHOLDER_RE = re.compile(r'"[^"\n]*%([.0-9]*[sdrf])')

_STDLIB_RE = re.compile(r"^(?:import logging|from logging import)", re.MULTILINE)
_LOGGER_DEF_RE = re.compile(r"logger\s*=\s*logging\.getLogger", re.MULTILINE)
_MODULO_RE = re.compile(r"%\s*\(")


def _is_stdlib_logging(path: Path) -> bool:
    """A module using the stdlib logger formats %-style natively."""
    text = path.read_text(encoding="utf-8")
    return bool(_STDLIB_RE.search(text) and _LOGGER_DEF_RE.search(text))


def _find_violations(path: Path) -> List[Tuple[int, str]]:
    text = path.read_text(encoding="utf-8")
    hits: List[Tuple[int, str]] = []
    for call in _CALL_RE.finditer(text):
        inner = call.group(1)
        if _PLACEHOLDER_RE.search(inner) is None:
            continue
        if _MODULO_RE.search(inner):
            # "...%s..." % (a, b) -> pre-formatted before loguru sees it.
            continue
        line_no = text[: call.start()].count("\n") + 1
        msg = _PLACEHOLDER_RE.search(inner)
        hits.append((line_no, msg.group(0)))
    return hits


def test_no_percent_style_loguru_placeholders() -> None:
    violations: List[Tuple[Path, int, str]] = []
    for root in SCAN_ROOTS:
        base = ROOT / root
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            if any(part in EXCLUDE_DIR_PARTS for part in path.parts):
                continue
            if _is_stdlib_logging(path):
                continue  # stdlib formats %-style correctly
            for line_no, placeholder in _find_violations(path):
                violations.append((path, line_no, placeholder))

    assert violations == [], (
        "loguru call site(s) still use %-style formatting (renders literal "
        f"placeholders, drops args): {violations}"
    )


def test_loguru_braces_render_values() -> None:
    """Brace formatting actually substitutes the positional argument."""
    from loguru import logger

    messages: List[str] = []

    class _Capture:
        def write(self, message: str) -> None:
            messages.append(message)

    logger_id = logger.add(_Capture(), format="{message}", level="INFO")
    try:
        logger.info("bulk saved {} articles", 7)
    finally:
        logger.remove(logger_id)

    assert messages and "7" in messages[0]
    assert "%" not in messages[0]


# ---------------------------------------------------------------------------
# Brace-regression guard
# ---------------------------------------------------------------------------

_LOGURU_LEVELS = frozenset(
    {"info", "warning", "error", "debug", "exception", "success", "critical"}
)
_RECEIVER_RE = re.compile(r"logger(?:\s*\.|$)")
_MODULO_RE = re.compile(r"%\s*\(")


def _unbalanced_brace(message: str) -> Optional[str]:
    """Return a description of the first unbalanced brace in ``message``.

    loguru formats messages like :meth:`str.format`: every ``{`` starts a
    field and every ``}`` closes one, with ``{{``/``}}`` as literal escapes.
    An unbalanced brace raises at render time (KeyError/IndexError/ValueError),
    so the guard flags them the same way a runtime would. Nested replacement
    fields (``{name:{width}}``) are not used anywhere in this codebase and are
    intentionally flagged to keep the scanner simple.
    """
    i = 0
    n = len(message)
    while i < n:
        char = message[i]
        if char == "{":
            if i + 1 < n and message[i + 1] == "{":
                i += 2
                continue
            j = i + 1
            while j < n and message[j] != "}":
                if message[j] == "{":
                    return (
                        f"nested/extra `{{` at offset {j} (unexpected in flat fields)"
                    )
                j += 1
            if j >= n:
                return f"unclosed `{{` at offset {i}"
            i = j + 1
        elif char == "}":
            if i + 1 < n and message[i + 1] == "}":
                i += 2
                continue
            return f"single `}}` at offset {i}"
        else:
            i += 1
    return None


def _iter_loguru_message_literals(path: Path):
    """Yield (lineno, plain-str-literal message) for loguru call sites.

    Uses the AST so string concatenation and multi-line calls are captured
    reliably. Only plain string literal messages are checked; f-strings are
    already rendered at the call site. Sites that pre-build the message with
    ``%``-modulo (e.g. ``"..." % (a, b)``) are skipped: the braces, if any, are
    resolved before loguru ever sees the string.
    """
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in _LOGURU_LEVELS
            and isinstance(node.func.value, (ast.Name, ast.Call, ast.Attribute))
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            continue
        receiver = ast.get_source_segment(text, node.func.value) or "?"
        if not _RECEIVER_RE.match(receiver.strip()):
            continue
        call_src = ast.get_source_segment(text, node) or ""
        if _MODULO_RE.search(call_src):
            continue
        yield node.lineno, node.args[0].value


def test_no_unbalanced_braces_in_loguru_messages() -> None:
    violations: List[Tuple[Path, int, str]] = []
    for root in SCAN_ROOTS:
        base = ROOT / root
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            if any(part in EXCLUDE_DIR_PARTS for part in path.parts):
                continue
            if _is_stdlib_logging(path):
                continue  # %-format: braces are literal, not format fields
            for lineno, message in _iter_loguru_message_literals(path):
                problem = _unbalanced_brace(message)
                if problem is not None:
                    violations.append((path, lineno, f"{problem}: {message[:80]!r}"))

    assert violations == [], (
        "loguru message literal(s) have unbalanced braces — they raise at "
        f"render time: {violations}"
    )
