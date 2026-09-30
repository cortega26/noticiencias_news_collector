"""
Module role: Owns the target-repository publication stages for one approved
article — branch creation, post write, frontend validation, commit/push and PR
creation — composing the extracted TargetRepoWriter, GitHubPublisher and
PROrchestrator collaborators.

Owns:
- publish: run the publication stages in order and return a typed outcome
- PublicationRequest / PublicationDeps / PublicationOutcome

Does NOT own:
- Canonical identity and image resolution (upstream of AI editing)
- Editorial refinement and policy gates (`RefineryEngine`)
- Attempt persistence and optional-audit scheduling (`RefineryEngine`, so the
  engine keeps owning the attempt artifact and its compatibility delegates)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Optional, cast

from news_collector.contracts.publication_validation import PublicationFailureClass
from news_collector.logic.workflows.frontend_publication_validation import (
    run_frontend_publication_validation,
    validate_post_frontmatter_fast,
)
from news_collector.logic.workflows.publication_attempts import artifact_name
from news_collector.utils.logger import get_logger
from news_collector.validation.publication_repairs import repair_post_content

logger = get_logger().create_module_logger("TargetRepoPublication")

StageRecorder = Callable[..., None]


@dataclass(frozen=True)
class PublicationRequest:
    """One approved article ready for target-repository publication."""

    article: Dict[str, Any]
    article_id: str
    numeric_id: Optional[int]
    output_filename: Optional[str]
    refined_content: str
    grounding_notes: str
    target_repo_obj: Any
    target_dir: Path
    attempts_dir: Path


@dataclass(frozen=True)
class PublicationDeps:
    """Collaborators read from the engine at publish time, never captured at
    construction (tests replace `engine.git`/`engine.writer` post-init)."""

    writer: Any
    git: Any
    pr_orchestrator: Any
    db: Any


@dataclass(frozen=True)
class PublicationOutcome:
    """Typed result of the target-repository publication stages."""

    success: bool
    branch_name: Optional[str] = None
    pr_url: Optional[str] = None
    validation_summary_path: Optional[str] = None
    failure_class: Optional[PublicationFailureClass] = None


@dataclass(frozen=True)
class _ValidationResult:
    ok: bool
    summary_path: Optional[str] = None
    failure_class: Optional[PublicationFailureClass] = None


class TargetRepoPublicationWorkflow:
    """Publishes one article: branch -> write -> validate -> commit/push -> PR.

    Every collaborator is injected per call through `PublicationDeps`; the
    workflow holds no state and never touches attempt files or the auditor.
    """

    def publish(
        self,
        request: PublicationRequest,
        deps: PublicationDeps,
        record_stage: StageRecorder,
    ) -> PublicationOutcome:
        if not request.output_filename:
            logger.error(
                f"Cannot proceed without output_filename for {request.article_id}"
            )
            record_stage("output_filename", False)
            return PublicationOutcome(success=False)

        output_filename = request.output_filename
        branch_name, publishing_token = self._create_publication_branch(
            request, deps, output_filename, record_stage
        )
        if not self._write_post(request, deps, output_filename, record_stage):
            self._release_publishing_state(
                request,
                deps,
                record_stage,
                reason="file_write_failed",
                branch_name=publishing_token,
            )
            return PublicationOutcome(success=False, branch_name=branch_name)
        validation = self._validate_post_frontend(
            request, output_filename, record_stage
        )
        if not validation.ok:
            self._release_publishing_state(
                request,
                deps,
                record_stage,
                reason="frontend_validation_failed",
                failure_class=validation.failure_class,
                branch_name=publishing_token,
            )
            return PublicationOutcome(
                success=False,
                branch_name=branch_name,
                validation_summary_path=validation.summary_path,
                failure_class=validation.failure_class,
            )
        self._commit_and_push(request, deps, output_filename, branch_name, record_stage)
        pr_url = self._create_pr(request, deps, output_filename, branch_name)
        if not pr_url:
            logger.error("Failed to create PR.")
            record_stage("pr_created", False)
            return PublicationOutcome(
                success=False,
                branch_name=branch_name,
                # Preserve a falsy non-None PR value (e.g. "") exactly as the
                # pre-extraction engine persisted it.
                pr_url=pr_url,
                validation_summary_path=validation.summary_path,
            )
        logger.info(f"Pull Request created successfully: {pr_url}")
        record_stage("pr_created", True, pr_url=pr_url)
        return PublicationOutcome(
            success=True,
            branch_name=branch_name,
            pr_url=pr_url,
            validation_summary_path=validation.summary_path,
        )

    def _create_publication_branch(
        self,
        request: PublicationRequest,
        deps: PublicationDeps,
        output_filename: str,
        record_stage: StageRecorder,
    ) -> tuple[str, str]:
        """4. Create Branch: before writing files, so branch collisions or
        remote sync failures do not leave uncommitted content edits behind.

        Returns ``(branch_name, publishing_token)`` — the token is the exact
        branch name recorded by ``mark_article_publishing``, used to scope a
        later release to this run's attempt (overlapping publishers).
        """
        branch_slug = output_filename.replace(".md", "")
        expected_branch = f"content/update-{branch_slug}"

        # B-01 / F-0012: Mark as "publishing" BEFORE git operations
        if request.numeric_id is not None and hasattr(
            deps.db, "mark_article_publishing"
        ):
            try:
                deps.db.mark_article_publishing(request.numeric_id, expected_branch)
                logger.info(
                    f"Marked article {request.article_id} as 'publishing' "
                    f"(branch: {expected_branch})"
                )
            except Exception as e:
                logger.error(f"Failed to mark article as publishing: {e}")

        branch_name = cast(
            str,
            deps.git.create_branch(
                request.target_repo_obj,
                branch_prefix="content/update",
                explicit_name=branch_slug,
            ),
        )
        record_stage("branch_created", True, branch_name=branch_name)
        return branch_name, expected_branch

    def _write_post(
        self,
        request: PublicationRequest,
        deps: PublicationDeps,
        output_filename: str,
        record_stage: StageRecorder,
    ) -> bool:
        """5. Save File."""
        try:
            deps.writer.write_article(
                posts_dir=request.target_dir / "src/content/posts",
                output_filename=output_filename,
                content=request.refined_content,
                article_id=request.article_id,
                target_dir=request.target_dir,
            )
        except ValueError as e:
            logger.error("S0 GUARD: {}", e)
            record_stage("file_written", False, error=str(e))
            return False
        record_stage("file_written", True, output_filename=output_filename)
        return True

    def _validate_post_frontend(
        self,
        request: PublicationRequest,
        output_filename: str,
        record_stage: StageRecorder,
    ) -> _ValidationResult:
        if not (request.target_dir / "package.json").exists():
            record_stage(
                "frontend_publication_validation",
                True,
                skipped=True,
                reason="frontend_workspace_not_detected",
            )
            return _ValidationResult(ok=True)
        summary_path = str(
            request.attempts_dir
            / f"{artifact_name(request.article_id)}.frontend_validation.json"
        )
        fast = self._fast_frontmatter_guard(request, output_filename, record_stage)
        if not fast.ok and self._attempt_self_repair(
            request, output_filename, fast.failure_class, record_stage
        ):
            fast = self._fast_frontmatter_guard(request, output_filename, record_stage)
        if not fast.ok:
            return _ValidationResult(
                ok=False,
                summary_path=summary_path,
                failure_class=fast.failure_class,
            )
        full = self._run_full_frontend_validation(
            request, output_filename, summary_path, record_stage
        )
        if not full.ok and self._attempt_self_repair(
            request, output_filename, full.failure_class, record_stage
        ):
            full = self._run_full_frontend_validation(
                request, output_filename, summary_path, record_stage
            )
        if not full.ok:
            return _ValidationResult(
                ok=False,
                summary_path=summary_path,
                failure_class=full.failure_class,
            )
        return _ValidationResult(ok=True, summary_path=summary_path)

    def _attempt_self_repair(
        self,
        request: PublicationRequest,
        output_filename: str,
        failure_class: Optional[PublicationFailureClass],
        record_stage: StageRecorder,
    ) -> bool:
        """Apply one deterministic repair for a classified validation failure.

        Bounded by construction: one attempt per validation phase (the
        caller re-runs the phase at most once); no strategy → no re-run. The
        post is only rewritten when the pure strategy returned a repaired
        version that restores its contract.
        """
        if not failure_class:
            return False
        post_path = request.target_dir / "src/content/posts" / output_filename
        try:
            content = post_path.read_text(encoding="utf-8")
        except OSError as e:
            logger.warning(
                "Self-repair skipped for {}: cannot read post ({}): {}",
                request.article_id,
                post_path,
                e,
            )
            return False
        repair = repair_post_content(content, failure_class)
        if repair is None:
            return False
        try:
            post_path.write_text(repair.content, encoding="utf-8")
        except OSError as e:
            logger.warning(
                "Self-repair for {} could not write the post: {}",
                request.article_id,
                e,
            )
            return False
        logger.warning(
            "Self-corrected publication failure {} for article {}: {}",
            failure_class,
            request.article_id,
            "; ".join(repair.descriptions),
        )
        record_stage(
            "validation_self_repair",
            True,
            failure_class=failure_class,
            fields=list(repair.fields),
            descriptions=list(repair.descriptions),
        )
        return True

    def _release_publishing_state(
        self,
        request: PublicationRequest,
        deps: PublicationDeps,
        record_stage: StageRecorder,
        *,
        reason: str,
        failure_class: Optional[PublicationFailureClass] = None,
        branch_name: Optional[str] = None,
    ) -> None:
        """Undo the pre-PR `publishing` mark after a clean failure.

        A validation/write failure before commit/push can never become a PR,
        so leaving the article in `publishing` would force the next attempt
        through the crash-recovery path for nothing (and did exactly that on
        run 59). Recovery still owns failures after commit/push: those may
        have a pushed branch worth resuming.

        `branch_name` is the ownership token recorded by
        `mark_article_publishing`: a stale run must not release an article
        that a newer overlapping run has already re-marked.
        """
        if request.numeric_id is None or not hasattr(
            deps.db, "release_article_publishing"
        ):
            return
        try:
            released = deps.db.release_article_publishing(
                request.numeric_id,
                reason=reason,
                failure_class=failure_class,
                branch_name=branch_name,
            )
        except Exception as e:
            logger.warning(
                "Could not release publishing state for article {}: {}",
                request.article_id,
                e,
            )
            return
        if released:
            logger.info(
                "Released publishing state for article {} (reason: {})",
                request.article_id,
                reason,
            )
            record_stage(
                "publishing_state_released",
                True,
                reason=reason,
                failure_class=failure_class,
            )

    def _fast_frontmatter_guard(
        self,
        request: PublicationRequest,
        output_filename: str,
        record_stage: StageRecorder,
    ) -> _ValidationResult:
        # Fast, dependency-free frontmatter check first (plan 057): the
        # full frontend build below is slow and duplicates the frontend
        # CI. Catching schema violations (e.g. sources[].date: null)
        # here aborts in milliseconds instead of after a full npm
        # ci + prettier + lint + build cycle.
        fast_ok, fast_class, fast_error = validate_post_frontmatter_fast(
            request.target_dir / "src/content/posts" / output_filename
        )
        if fast_ok:
            return _ValidationResult(ok=True)
        failure_class = fast_class or "taxonomy_contract_violation"
        logger.error(
            "Fast frontmatter validation failed for {}: {}",
            request.article_id,
            fast_error,
        )
        record_stage(
            "frontend_publication_validation",
            False,
            failure_class=failure_class,
            fast=True,
            error=fast_error,
        )
        return _ValidationResult(ok=False, failure_class=failure_class)

    def _run_full_frontend_validation(
        self,
        request: PublicationRequest,
        output_filename: str,
        summary_path: str,
        record_stage: StageRecorder,
    ) -> _ValidationResult:
        validation_summary = run_frontend_publication_validation(
            request.target_dir,
            summary_output_path=Path(summary_path),
            stage_fixture=False,
            post_path=request.target_dir / "src/content/posts" / output_filename,
            install_dependencies=not (request.target_dir / "node_modules").exists(),
        )
        record_stage(
            "frontend_publication_validation",
            validation_summary.success,
            failure_class=validation_summary.overall_failure_class,
            summary_path=summary_path,
        )
        return _ValidationResult(
            ok=validation_summary.success,
            failure_class=validation_summary.overall_failure_class,
        )

    def _commit_and_push(
        self,
        request: PublicationRequest,
        deps: PublicationDeps,
        output_filename: str,
        branch_name: str,
        record_stage: StageRecorder,
    ) -> None:
        """6. Commit & Push."""
        deps.git.commit_and_push(
            request.target_repo_obj,
            f"Update article: {output_filename}",
            branch_name,
        )
        record_stage("commit_pushed", True, branch_name=branch_name)

    def _create_pr(
        self,
        request: PublicationRequest,
        deps: PublicationDeps,
        output_filename: str,
        branch_name: str,
    ) -> str | None:
        pr_result = deps.pr_orchestrator.create_pr(
            article_id=request.article_id,
            article=request.article,
            branch_name=branch_name,
            output_filename=output_filename,
            git_handler=deps.git,
            review_notes=request.grounding_notes,
        )
        return cast(Optional[str], pr_result.pr_url)
