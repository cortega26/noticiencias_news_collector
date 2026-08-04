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

import re
import sys
from pathlib import Path
from typing import List, Tuple

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
