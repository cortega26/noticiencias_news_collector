"""
Module role: Owns the publication-attempt artifact format — filename
derivation, canonical JSON persistence, interrupted-attempt preservation, and
read-back for the workflow/admin consumers.

Owns:
- artifact_name: sanitized filename stem for an article id
- persist_publication_attempt: write the PublicationAttemptSummary JSON
- persist_interrupted_attempt: persist accumulated stages after an unexpected
  raise without ever destroying a prior successful attempt record
- read_publication_attempt: exact-match read-back of one attempt summary

Does NOT own:
- The attempts directory (the caller owns and passes it, so tests and config
  can redirect it per-instance)
- Durable lifecycle rows (`db.lifecycle`, plan 060 Phase 3c dual-write)
- Deciding when an attempt starts or whether it succeeded
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional

from news_collector.contracts import (
    PublicationAttemptStageResult,
    PublicationAttemptSummary,
)
from news_collector.contracts.publication_validation import PublicationFailureClass
from news_collector.utils.logger import get_logger

logger = get_logger().create_module_logger("PublicationAttempts")


@dataclass(frozen=True)
class PublicationAttempt:
    """Input record for one persisted attempt artifact."""

    article_id: str
    success: bool
    stages: List[PublicationAttemptStageResult] = field(default_factory=list)
    target_repo: Optional[str] = None
    output_filename: Optional[str] = None
    final_slug: Optional[str] = None
    branch_name: Optional[str] = None
    pr_url: Optional[str] = None
    validation_summary_path: Optional[str] = None
    failure_class: Optional[PublicationFailureClass] = None


def artifact_name(article_id: str) -> str:
    """Return the sanitized filename stem for one article's attempt file."""
    safe_article_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", article_id).strip("_")
    return safe_article_id or "unknown"


def _summary_path(attempts_dir: Path, article_id: str) -> Path:
    return attempts_dir / f"{artifact_name(article_id)}.json"


def persist_publication_attempt(
    attempts_dir: Path, attempt: PublicationAttempt
) -> Path:
    """Write the canonical attempt summary JSON and return its path."""
    summary = PublicationAttemptSummary(
        generated_at=datetime.now(timezone.utc).isoformat(),
        article_id=attempt.article_id,
        target_repo=attempt.target_repo,
        output_filename=attempt.output_filename,
        final_slug=attempt.final_slug,
        branch_name=attempt.branch_name,
        pr_url=attempt.pr_url,
        validation_summary_path=attempt.validation_summary_path,
        success=attempt.success,
        failure_class=attempt.failure_class,
        stages=attempt.stages,
    )

    summary_path = _summary_path(attempts_dir, attempt.article_id)
    summary_path.write_text(
        json.dumps(summary.model_dump(mode="json"), indent=2),
        encoding="utf-8",
    )
    return summary_path


def _has_successful_attempt(attempts_dir: Path, article_id: str) -> bool:
    summary_path = _summary_path(attempts_dir, article_id)
    try:
        if not summary_path.is_file():
            return False
        existing = json.loads(summary_path.read_text(encoding="utf-8"))
        return isinstance(existing, dict) and existing.get("success") is True
    except (OSError, ValueError) as exc:
        logger.warning(f"Could not inspect prior attempt file for {article_id}: {exc}")
        return False


def persist_interrupted_attempt(
    attempts_dir: Path,
    article_id: str,
    stages: Optional[List[PublicationAttemptStageResult]],
) -> None:
    """Persist accumulated stages when `process_single_article` raised
    unexpectedly (plan 069), so failed runs still show a stage checklist
    in the quality review loop.

    Never overwrites an existing *successful* attempt file (a re-publish
    crash must not destroy the prior PR record); never raises; keeps
    `failure_class` unset (the contract Literal has no generic member —
    the workflow row already carries the error).
    """
    if not article_id or article_id == "unknown" or not stages:
        return
    if _has_successful_attempt(attempts_dir, article_id):
        logger.info(
            f"Keeping prior successful attempt file for {article_id}; "
            "not overwriting with the interrupted run."
        )
        return
    try:
        persist_publication_attempt(
            attempts_dir,
            PublicationAttempt(article_id=article_id, success=False, stages=stages),
        )
    except Exception as exc:
        logger.warning(f"Could not persist interrupted attempt for {article_id}: {exc}")


def read_publication_attempt(
    attempts_dir: Path, article_id: str
) -> dict[str, Any] | None:
    """Read `publication_attempts/{artifact_name(article_id)}.json`.

    Exact match only; a missing or malformed file returns None.
    """
    path = _summary_path(attempts_dir, article_id)
    try:
        if not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError) as exc:
        logger.warning("Could not read publication attempt summary: {}", exc)
        return None
