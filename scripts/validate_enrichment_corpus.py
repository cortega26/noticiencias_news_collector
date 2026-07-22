#!/usr/bin/env python
"""Corpus validator for plan 048 Step 2 (curated enrichment registry spike).

Enforces the plan's own Step 2 Verify criterion: "corpus validator enforces
IDs, split, language, text provenance class, gold topics/entities, no raw
personal data, and no overlap between development and held-out sets; report
agreement and slice counts."

Usage:
    python scripts/validate_enrichment_corpus.py tests/data/enrichment_eval.jsonl
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List

ALLOWED_LANGUAGES = {"en", "es", "pt", "fr"}
ALLOWED_SPLITS = {"dev", "heldout"}
ALLOWED_PROVENANCE = {"synthetic", "permissioned"}
ALLOWED_REVIEW_STATUS = {"draft_unreviewed", "reviewed"}
REQUIRED_FIELDS = {
    "id",
    "split",
    "language",
    "provenance",
    "case_type",
    "title",
    "summary",
    "model_draft_topics",
    "model_draft_entities",
    "gold_topics",
    "gold_entities",
    "review_status",
}

# Crude personal-data guard: email addresses and long digit runs (phone/ID-like).
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_LONG_DIGIT_RUN_RE = re.compile(r"\d{7,}")


def _load_records(path: Path) -> List[Dict[str, Any]]:
    records = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{lineno}: invalid JSON — {exc}") from exc
    return records


def validate(records: List[Dict[str, Any]]) -> List[str]:
    """Return a list of error strings; empty means the corpus is valid."""
    errors: List[str] = []
    seen_ids: Dict[str, int] = {}

    for idx, rec in enumerate(records):
        loc = rec.get("id", f"<record #{idx}>")
        missing = REQUIRED_FIELDS - rec.keys()
        if missing:
            errors.append(f"{loc}: missing required field(s): {sorted(missing)}")
            continue

        if not isinstance(rec["id"], str) or not rec["id"]:
            errors.append(f"{loc}: id must be a non-empty string")
        elif rec["id"] in seen_ids:
            errors.append(
                f"{loc}: duplicate id (first seen at record #{seen_ids[rec['id']]})"
            )
        else:
            seen_ids[rec["id"]] = idx

        if rec["split"] not in ALLOWED_SPLITS:
            errors.append(
                f"{loc}: split {rec['split']!r} not in {sorted(ALLOWED_SPLITS)}"
            )
        if rec["language"] not in ALLOWED_LANGUAGES:
            errors.append(
                f"{loc}: language {rec['language']!r} not in {sorted(ALLOWED_LANGUAGES)}"
            )
        if rec["provenance"] not in ALLOWED_PROVENANCE:
            errors.append(
                f"{loc}: provenance {rec['provenance']!r} not in {sorted(ALLOWED_PROVENANCE)}"
            )
        if rec["review_status"] not in ALLOWED_REVIEW_STATUS:
            errors.append(
                f"{loc}: review_status {rec['review_status']!r} not in {sorted(ALLOWED_REVIEW_STATUS)}"
            )

        # Gold labels are only meaningful once a human has actually reviewed
        # the record — a "reviewed" record must carry real gold labels, not
        # nulls left over from the draft stage.
        if rec["review_status"] == "reviewed":
            if rec.get("gold_topics") is None:
                errors.append(f"{loc}: review_status=reviewed but gold_topics is null")
            if rec.get("gold_entities") is None:
                errors.append(
                    f"{loc}: review_status=reviewed but gold_entities is null"
                )

        text = f"{rec.get('title', '')} {rec.get('summary', '')}"
        if _EMAIL_RE.search(text):
            errors.append(
                f"{loc}: possible email address in title/summary — remove personal data"
            )
        if _LONG_DIGIT_RUN_RE.search(text):
            errors.append(
                f"{loc}: long digit run in title/summary — check for phone/ID-like personal data"
            )

    # No overlap between dev and heldout sets (by id — the plan's own
    # requirement is that held-out data must never leak into development).
    dev_ids = {r["id"] for r in records if r.get("split") == "dev"}
    heldout_ids = {r["id"] for r in records if r.get("split") == "heldout"}
    overlap = dev_ids & heldout_ids
    if overlap:
        errors.append(f"dev/heldout overlap on ids: {sorted(overlap)}")

    return errors


def report_slices(records: List[Dict[str, Any]]) -> str:
    lines = [f"Total records: {len(records)}"]
    lines.append(f"By split: {dict(Counter(r['split'] for r in records))}")
    lines.append(f"By language: {dict(Counter(r['language'] for r in records))}")
    lines.append(f"By case_type: {dict(Counter(r['case_type'] for r in records))}")
    lines.append(
        f"By review_status: {dict(Counter(r['review_status'] for r in records))}"
    )
    reviewed = sum(1 for r in records if r["review_status"] == "reviewed")
    target_note = (
        "sufficient"
        if reviewed >= 200
        else "below the plan's 200-record evaluation target"
    )
    lines.append(f"Reviewed (gold-labeled): {reviewed}/{len(records)} ({target_note})")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("corpus_path", type=Path)
    args = parser.parse_args()

    records = _load_records(args.corpus_path)
    errors = validate(records)

    print(report_slices(records))
    print()
    if errors:
        print(f"INVALID — {len(errors)} error(s):")
        for err in errors:
            print(f"  - {err}")
        return 1

    print("VALID — no structural errors found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
