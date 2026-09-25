"""
Module role: Optional post-PR editorial auditor lifecycle — backpressure,
background submission, callback result parsing, and audit-status persistence.

Owns:
- schedule: submit one bounded audit task unless a previous one is still
  running (backpressure) and persist every outcome through the caller's
  status recorder
- record_status: best-effort `article_metadata["audit"]` writes
- last_future: the in-flight future used for backpressure

Does NOT own:
- Whether an article should be audited (the engine's `should_run_fast` check)
- The threadpool (the caller injects it, so tests can run audits inline)
- Audit execution itself (`EditorialAuditor.audit_article_sync`)
"""

from __future__ import annotations

import concurrent.futures
from typing import Any, Callable, Dict, Optional

from news_collector.utils.logger import get_logger

logger = get_logger().create_module_logger("AuditScheduler")


class AuditScheduler:
    """State machine for the non-blocking, best-effort post-PR audit.

    The auditor, executor and status recorder are injected per `schedule`
    call (not captured at construction) so the engine's existing test seams —
    `engine.auditor = MagicMock()`, `engine.executor = _ImmediateExecutor()`,
    `patch.object(engine, "_record_audit_status")` — keep working.
    """

    def __init__(self, db: Any) -> None:
        self._db = db
        self._last_future: Optional[concurrent.futures.Future] = None

    # ------------------------------------------------------------------
    # backpressure state
    # ------------------------------------------------------------------

    @property
    def last_future(self) -> Optional[concurrent.futures.Future]:
        return self._last_future

    @last_future.setter
    def last_future(self, value: Optional[concurrent.futures.Future]) -> None:
        self._last_future = value

    # ------------------------------------------------------------------
    # status persistence
    # ------------------------------------------------------------------

    def record_status(
        self,
        article_numeric_id: int | None,
        status: str,
        reason: str,
        attempts: int,
        timeout_seconds: int | None = None,
        model: str | None = None,
        endpoint: str | None = None,
    ) -> None:
        if article_numeric_id is None:
            return
        update_status = getattr(self._db, "update_article_audit_status", None)
        if not callable(update_status):
            return
        try:
            update_status(
                article_numeric_id,
                status,
                reason,
                attempts=attempts,
                timeout_seconds=timeout_seconds,
                model=model,
                endpoint=endpoint,
            )
        except Exception as e:
            logger.warning(
                f"Failed to persist audit status for article {article_numeric_id}: {e}"
            )

    # ------------------------------------------------------------------
    # scheduling
    # ------------------------------------------------------------------

    def schedule(
        self,
        *,
        auditor: Any,
        executor: concurrent.futures.Executor,
        status_recorder: Callable[..., None],
        article_id: str,
        article_numeric_id: int | None,
        content: str,
        source_url: str,
        article_data: Dict[str, Any],
    ) -> None:
        try:
            if self._last_future and not self._last_future.done():
                logger.warning(
                    f"Auditor Backpressure: Skipping audit for {article_id} (Previous task still active)"
                )
                status_recorder(
                    article_numeric_id=article_numeric_id,
                    status="audit_skipped_backpressure",
                    reason="Skipped because previous audit task is still running.",
                    attempts=0,
                )
                return

            logger.info(
                f"Submitting optional auditor task for {article_id} after PR creation."
            )
            future = executor.submit(
                auditor.audit_article_sync,
                article_id=article_id,
                content=content,
                source_url=source_url,
                article_data=article_data,
            )
            self._last_future = future

            def _on_done(done_future):
                try:
                    audit_result = done_future.result() or {}
                except Exception as exc:
                    message = (
                        f"Optional auditor task crashed for article {article_id}: {exc}"
                    )
                    logger.warning(message)
                    status_recorder(
                        article_numeric_id=article_numeric_id,
                        status="audit_failed",
                        reason=message,
                        attempts=0,
                    )
                    return

                if not isinstance(audit_result, dict):
                    audit_result = {
                        "status": "audit_failed",
                        "reason": (
                            f"invalid_audit_result_type:{type(audit_result).__name__}"
                        ),
                        "attempts": 0,
                    }

                status = str(audit_result.get("status", "audit_failed"))
                reason = str(audit_result.get("reason", "unknown"))
                attempts_raw = audit_result.get("attempts", 0)
                try:
                    attempts = int(attempts_raw or 0)
                except (TypeError, ValueError):
                    attempts = 0
                timeout_seconds = audit_result.get("timeout_seconds")
                try:
                    timeout_int = int(timeout_seconds) if timeout_seconds else None
                except (TypeError, ValueError):
                    timeout_int = None
                model = audit_result.get("model")
                endpoint = audit_result.get("endpoint")

                status_recorder(
                    article_numeric_id=article_numeric_id,
                    status=status,
                    reason=reason,
                    attempts=attempts,
                    timeout_seconds=timeout_int,
                    model=str(model) if model else None,
                    endpoint=str(endpoint) if endpoint else None,
                )

                if status != "audit_passed":
                    logger.warning(
                        "Optional auditor did not pass for article {}: {}",
                        article_id,
                        reason,
                    )

            future.add_done_callback(_on_done)

        except Exception as e:
            logger.warning(f"Auditor submission failed for {article_id}: {e}")
            status_recorder(
                article_numeric_id=article_numeric_id,
                status="audit_failed",
                reason=f"submission_failed: {e}",
                attempts=0,
            )
