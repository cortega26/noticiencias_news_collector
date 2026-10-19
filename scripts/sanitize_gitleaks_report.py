#!/usr/bin/env python3
"""Write a gitleaks JSON report copy with matched secret values redacted.

The CI secret scan runs gitleaks without ``--redact`` because baseline
matching is content-based (redacting the match would disable
``.gitleaks-baseline.json``), so the raw report carries the matched value in
its ``Secret`` and ``Match`` fields. The raw report must feed the gate step
only: this script produces the copy that is safe to upload as a CI artifact
on a public repository. Rule id, description, file, line, commit, author,
date, and all other triage fields are preserved; ``Secret`` and ``Match``
values are replaced with a fixed marker.

Policy point (plan 142): if gitleaks changes its report schema, update this
sanitiser in the same change as the ``GITLEAKS_VERSION`` pin in
``.github/workflows/quality.yml``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REDACTED_VALUE = "[redacted by sanitize_gitleaks_report.py]"

# gitleaks JSON report fields that carry the matched value itself (shape
# confirmed against the committed .gitleaks-baseline.json and the installed
# gitleaks report format). Matched case-insensitively.
_REDACTED_KEYS = frozenset({"secret", "match"})


def _sanitize_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """Return one report entry with every matched-value field replaced."""
    return {
        key: (REDACTED_VALUE if key.lower() in _REDACTED_KEYS else value)
        for key, value in entry.items()
    }


def sanitize_report(records: Any) -> list[dict[str, Any]]:
    """Return report entries with ``Secret``/``Match`` values replaced.

    Fails closed with ``ValueError`` when the payload is not a JSON array of
    objects — writing an unexpected shape is worse than not writing at all.
    """
    if not isinstance(records, list):
        raise ValueError("gitleaks report must be a JSON array of findings")
    sanitized: list[dict[str, Any]] = []
    for entry in records:
        if not isinstance(entry, dict):
            raise ValueError("gitleaks report entries must be JSON objects")
        sanitized.append(_sanitize_entry(entry))
    return sanitized


def sanitize_file(source: Path, destination: Path) -> int:
    """Write the sanitized copy of *source* to *destination*.

    A missing or empty source (a scan that found nothing, or a step that
    never produced a report) writes an empty array: the upload step may run
    with ``if: always()``, and it must never fall back to raw content.
    Returns the number of findings written.
    """
    payload: Any = []
    if source.exists() and source.read_text(encoding="utf-8").strip():
        payload = json.loads(source.read_text(encoding="utf-8"))

    sanitized = sanitize_report(payload)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(sanitized, indent=2) + "\n", encoding="utf-8")
    return len(sanitized)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Raw gitleaks JSON report.")
    parser.add_argument(
        "destination", type=Path, help="Where to write the sanitized copy."
    )
    args = parser.parse_args(argv)

    try:
        count = sanitize_file(args.source, args.destination)
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"[sanitize_gitleaks_report] failed: {exc}", file=sys.stderr)
        return 1

    print(
        "[sanitize_gitleaks_report] wrote "
        f"{count} sanitized finding(s) to {args.destination}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
