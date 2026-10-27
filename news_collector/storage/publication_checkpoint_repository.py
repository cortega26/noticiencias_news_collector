"""Atomic checkpoint and parked-run storage for publication workflows."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from pydantic import TypeAdapter
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from news_collector.contracts.publication_checkpoint import (
    PublicationCheckpoint,
    PublicationItemOutcome,
)
from news_collector.storage.models import Article, WorkflowRun
from news_collector.utils.logger import get_logger

if TYPE_CHECKING:
    from news_collector.storage.database import DatabaseManager


logger = get_logger().create_module_logger(__name__)
_CHECKPOINTS = TypeAdapter(dict[str, PublicationCheckpoint])
_OUTCOMES = TypeAdapter(dict[str, PublicationItemOutcome])


class PublicationCheckpointRepository:
    """Own JSON checkpoint writes; workflow code never writes draft data directly."""

    def __init__(self, db: DatabaseManager):
        self.db = db

    def load(self, run_id: int, article_id: str) -> PublicationCheckpoint | None:
        with self.db.get_session() as session:
            row = session.get(WorkflowRun, run_id)
            value = (
                (row.run_metadata or {}).get("checkpoints", {}).get(str(article_id))
                if row
                else None
            )
        return PublicationCheckpoint.model_validate(value) if value else None

    def save(self, run_id: int, checkpoint: PublicationCheckpoint) -> None:
        self._save_item(
            run_id,
            "checkpoints",
            checkpoint.article_id,
            checkpoint.model_dump(mode="json"),
        )

    def save_outcome(self, run_id: int, outcome: PublicationItemOutcome) -> None:
        """Persist rejected siblings too, even if they never produced a draft."""
        self._save_item(
            run_id, "item_outcomes", outcome.article_id, outcome.model_dump(mode="json")
        )

    def outcomes(self, run_id: int) -> dict[str, PublicationItemOutcome]:
        with self.db.get_session() as session:
            row = session.get(WorkflowRun, run_id)
            values = (row.run_metadata or {}).get("item_outcomes", {}) if row else {}
        return _OUTCOMES.validate_python(values)

    def _save_item(
        self, run_id: int, section: str, article_id: str, value: dict
    ) -> None:
        # The publication worker is single-flight; heartbeat writes touch only
        # timestamps. CAS on the previous JSON prevents losing progress updates.
        for _ in range(5):
            with self.db.get_session() as session:
                row = session.get(WorkflowRun, run_id)
                if (
                    row is None
                    or row.run_type != "publication"
                    or row.status != "running"
                ):
                    raise RuntimeError(
                        "Checkpoint requires the owning running publication"
                    )
                old = row.run_metadata or {}
                items = {**old.get(section, {}), article_id: value}
                changed = session.execute(
                    update(WorkflowRun)
                    .where(
                        WorkflowRun.id == run_id,
                        WorkflowRun.status == "running",
                        WorkflowRun.run_metadata == old,
                    )
                    .values(
                        run_metadata={**old, section: items},
                        updated_at=datetime.now(timezone.utc),
                    )
                )
                if changed.rowcount == 1:
                    return
        raise RuntimeError("Checkpoint update conflicted repeatedly")

    def all(self, run_id: int) -> dict[str, PublicationCheckpoint]:
        with self.db.get_session() as session:
            row = session.get(WorkflowRun, run_id)
            values = (row.run_metadata or {}).get("checkpoints", {}) if row else {}
        return _CHECKPOINTS.validate_python(values)

    def reject_invalid_wait(self, run_id: int, detail: str) -> bool:
        """Keep damaged evidence for inspection without starving other requests."""
        with self.db.get_session() as session:
            result = session.execute(
                update(WorkflowRun)
                .where(
                    WorkflowRun.id == run_id,
                    WorkflowRun.run_type == "publication",
                    WorkflowRun.status == "waiting_for_image",
                )
                .values(
                    status="failed",
                    error_code="invalid_publication_checkpoint",
                    error_detail=detail,
                    heartbeat_at=None,
                    finished_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                )
            )
            return bool(result.rowcount == 1)

    def park(self, run_id: int, summary: dict) -> bool:
        with self.db.get_session() as session:
            row = session.get(WorkflowRun, run_id)
            if row is None or row.status != "running":
                return False
            metadata = {**(row.run_metadata or {}), "summary": summary}
            result = session.execute(
                update(WorkflowRun)
                .where(
                    WorkflowRun.id == run_id,
                    WorkflowRun.status == "running",
                )
                .values(
                    status="waiting_for_image",
                    run_metadata=metadata,
                    heartbeat_at=None,
                    finished_at=None,
                    error_code=None,
                    error_detail=None,
                    updated_at=datetime.now(timezone.utc),
                )
            )
            return bool(result.rowcount == 1)

    def claim(self, run_id: int) -> bool:
        try:
            with self.db.get_session() as session:
                row = session.get(WorkflowRun, run_id)
                if row is None or row.status != "waiting_for_image":
                    return False
                previous = row.run_metadata or {}
                try:
                    result = session.execute(
                        update(WorkflowRun)
                        .where(
                            WorkflowRun.id == run_id,
                            WorkflowRun.status == "waiting_for_image",
                            WorkflowRun.run_metadata == previous,
                        )
                        .values(
                            status="queued",
                            run_metadata={**previous, "worker_pid": os.getpid()},
                            heartbeat_at=datetime.now(timezone.utc),
                            finished_at=None,
                            updated_at=datetime.now(timezone.utc),
                        )
                    )
                except IntegrityError:
                    # Expected race: another publication holds the global slot.
                    # Roll back here so get_session does not log it as an error.
                    session.rollback()
                    return False
                return bool(result.rowcount == 1)
        except IntegrityError:
            return False  # another queued/running publication owns the global slot

    def waiting(self) -> list[tuple[int, dict]]:
        with self.db.get_session() as session:
            return [
                (int(row.id), dict(row.run_metadata or {}))
                for row in session.execute(
                    select(WorkflowRun)
                    .where(
                        WorkflowRun.run_type == "publication",
                        WorkflowRun.status == "waiting_for_image",
                    )
                    .order_by(WorkflowRun.id)
                ).scalars()
            ]

    def reusable_request(
        self,
        *,
        article_id: int | None = None,
        article_url: str | None = None,
        article_ids: list[int] | None = None,
    ) -> tuple[int, bool] | None:
        """Return the same pending/completed source revision, never changed text.

        A waiting snapshot remains recoverable if the source row disappears.
        Finished evidence is reusable only when the current source still proves
        the same revision. Media and workflow metadata do not change that revision.
        """
        with self.db.get_session() as session:
            rows = session.execute(
                select(WorkflowRun)
                .where(
                    WorkflowRun.run_type == "publication",
                    WorkflowRun.status.in_(("waiting_for_image", "succeeded")),
                )
                .order_by(WorkflowRun.id.desc())
            ).scalars()
            for row in rows:
                metadata = row.run_metadata or {}
                requested = self._matching_request_ids(
                    metadata, article_id, article_url, article_ids
                )
                if not requested:
                    continue
                try:
                    values = _CHECKPOINTS.validate_python(
                        metadata.get("checkpoints", {})
                    )
                    outcomes = _OUTCOMES.validate_python(
                        metadata.get("item_outcomes", {})
                    )
                except ValueError as exc:
                    logger.error(
                        "Publication run {} has invalid checkpoint evidence: {}",
                        row.id,
                        exc,
                    )
                    continue
                checkpoints = [values[key] for key in requested if key in values]
                if any(key not in values and key not in outcomes for key in requested):
                    continue
                if article_ids is None and (
                    (checkpoints and checkpoints[0].status == "failed")
                    or (not checkpoints and outcomes[requested[0]].status == "failed")
                ):
                    continue
                if row.status == "succeeded" and len(checkpoints) != len(requested):
                    continue
                matches = all(
                    self._source_revision_matches(
                        session,
                        checkpoint,
                        allow_missing=row.status == "waiting_for_image",
                    )
                    for checkpoint in checkpoints
                )
                if matches:
                    complete = len(checkpoints) == len(requested) and all(
                        cp.status == "succeeded" for cp in checkpoints
                    )
                    if row.status == "waiting_for_image" or complete:
                        return int(row.id), complete
        return None

    @staticmethod
    def _matching_request_ids(
        metadata: dict,
        article_id: int | None,
        article_url: str | None,
        article_ids: list[int] | None,
    ) -> list[str]:
        ids = [str(i) for i in metadata.get("article_ids", [])]
        values = metadata.get("checkpoints", {})
        if article_ids is not None:
            requested = [str(i) for i in article_ids]
            return requested if ids == requested else []
        if article_id is not None:
            key = str(article_id)
            return (
                [key]
                if key in values or key == str(metadata.get("article_id")) or key in ids
                else []
            )
        if article_url and metadata.get("article_url") == article_url:
            return list(values)
        return []

    @staticmethod
    def _source_revision_matches(
        session: Session, checkpoint: PublicationCheckpoint, *, allow_missing: bool
    ) -> bool:
        source = (
            session.get(Article, int(checkpoint.article_id))
            if checkpoint.article_id.isdecimal()
            else None
        )
        if source is None:
            return allow_missing
        return all(
            checkpoint.article.get(field) is None
            or checkpoint.article[field] == getattr(source, field)
            for field in ("title", "url", "content", "summary", "source_id")
        )

    def supersede_changed_waits(
        self,
        session: Session,
        *,
        article_ids: list[str],
        article_url: str | None = None,
    ) -> None:
        """Cancel stale revisions in the SAME transaction that accepts a new run.

        Other siblings stay pending. A conflicting enqueue rolls this update back.
        """
        rows = session.execute(
            select(WorkflowRun).where(
                WorkflowRun.run_type == "publication",
                WorkflowRun.status == "waiting_for_image",
            )
        ).scalars()
        for row in rows:
            original = row.run_metadata or {}
            try:
                checkpoints = _CHECKPOINTS.validate_python(
                    original.get("checkpoints", {})
                )
            except ValueError as exc:
                logger.error(
                    "Publication run {} has invalid checkpoint evidence: {}",
                    row.id,
                    exc,
                )
                continue
            requested = (
                set(checkpoints)
                if article_url and original.get("article_url") == article_url
                else set(article_ids)
            )
            changed = {
                key
                for key, cp in checkpoints.items()
                if key in requested
                and cp.status in {"ready", "waiting_for_image"}
                and not self._source_revision_matches(session, cp, allow_missing=True)
            }
            if not changed:
                continue
            metadata = self._superseded_metadata(original, checkpoints, changed)
            pending = any(
                value["status"] in {"ready", "waiting_for_image"}
                for value in metadata["checkpoints"].values()
            )
            values = {
                "run_metadata": metadata,
                "updated_at": datetime.now(timezone.utc),
            }
            if not pending:
                values.update(
                    status="cancelled",
                    finished_at=datetime.now(timezone.utc),
                    heartbeat_at=None,
                    error_code="source_revision_superseded",
                    error_detail="A newer explicit request superseded this source revision.",
                )
            session.execute(
                update(WorkflowRun)
                .where(
                    WorkflowRun.id == row.id,
                    WorkflowRun.status == "waiting_for_image",
                    WorkflowRun.run_metadata == original,
                )
                .values(**values)
            )

    @staticmethod
    def _superseded_metadata(
        original: dict, checkpoints: dict[str, PublicationCheckpoint], changed: set[str]
    ) -> dict:
        outcomes = dict(original.get("item_outcomes", {}))
        for key in changed:
            checkpoints[key] = checkpoints[key].model_copy(update={"status": "failed"})
            outcomes[key] = PublicationItemOutcome(
                article_id=key,
                status="failed",
                editorial_completed_count=1,
                error_code="source_revision_superseded",
                message="A newer explicit request superseded this source revision.",
            ).model_dump(mode="json")
        summary = dict(original.get("summary", {}))
        summary["waiting_for_image_count"] = max(
            0, summary.get("waiting_for_image_count", 0) - len(changed)
        )
        summary["failed_count"] = summary.get("failed_count", 0) + len(changed)
        if "items" in summary:
            summary["items"] = [
                (
                    {
                        **item,
                        "status": "failed",
                        "message": outcomes[str(item.get("article_id"))]["message"],
                    }
                    if str(item.get("article_id")) in changed
                    else item
                )
                for item in summary["items"]
            ]
        return {
            **original,
            "summary": summary,
            "item_outcomes": outcomes,
            "checkpoints": {
                key: cp.model_dump(mode="json") for key, cp in checkpoints.items()
            },
        }

    def standalone(self, article_ids: list[str]) -> int:
        with self.db.get_session() as session:
            row = WorkflowRun(
                run_type="publication",
                status="running",
                started_at=datetime.now(timezone.utc),
                run_metadata={
                    "article_ids": article_ids,
                    "standalone": True,
                    "worker_pid": os.getpid(),
                },
            )
            session.add(row)
            session.flush()
            return int(row.id)

    def finish_standalone(self, run_id: int, success: bool) -> None:
        with self.db.get_session() as session:
            session.execute(
                update(WorkflowRun)
                .where(
                    WorkflowRun.id == run_id,
                    WorkflowRun.status == "running",
                )
                .values(
                    status="succeeded" if success else "failed",
                    finished_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                )
            )
