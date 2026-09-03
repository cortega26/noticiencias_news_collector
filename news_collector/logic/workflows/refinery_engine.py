"""
Module role: Orchestrates the refinement pipeline to process articles using an editor agent, write them to a target repository, and manage Git operations.

Inputs:
- Dictionaries containing article data.
- Git repository objects and target directory paths.
- Configuration and database manager instances.

Outputs:
- Summary dictionaries of processed counts and errors.
- Boolean success indicators for single article processing.

Side effects:
- Writes Markdown files and JSON manifests to the local filesystem.
- Performs Git branching, committing, pushing, and creates pull requests on GitHub.
- Updates database states (e.g., canonical slugs, publication marks).
- Downloads images via HTTP.
- Appends to an enforcement log file.

Invariants:
- Re-processing reuses the original canonical identity to ensure URL immutability.
- Editorial policy is enforced before persistence, rejecting blocked articles.
- The pipeline handles images, optionally downloading them or using defaults on failure.

Failure modes:
- Returns False if policy validation fails or the auditor rejects content.
- Continues on individual article errors, recording them in the summary errors list.
- Fallback behaviors trigger on missing data (e.g., generating fallback slugs or using current dates).
"""

import concurrent.futures
import contextlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, cast

from news_collector.components.editorial.ai_editor import EditorAgent
from news_collector.components.editorial.auditor import EditorialAuditor
from news_collector.components.publishing import GitHubPublisher
from news_collector.contracts import (
    PublicationAttemptStageResult,
    PublicationAttemptSummary,
)
from news_collector.contracts.publication_validation import PublicationFailureClass
from news_collector.logic.workflows.frontend_publication_validation import (
    run_frontend_publication_validation,
    validate_post_frontmatter_fast,
)
from news_collector.logic.workflows.image_briefs import ImageBriefStore
from news_collector.logic.workflows.image_handler import (
    CT_TO_EXT,
    ArticleImageHandler,
    publication_safe_image_alt,
)
from news_collector.logic.workflows.pr_orchestrator import PROrchestrator
from news_collector.logic.workflows.publication_identity import (
    PublicationIdentityResolver,
)
from news_collector.logic.workflows.target_repo_writer import TargetRepoWriter
from news_collector.utils.logger import get_logger
from news_collector.utils.slug import slugify

if "TYPE_CHECKING":
    from news_collector.storage.database import DatabaseManager

logger = get_logger().create_module_logger("RefineryEngine")

# Removing duplicate import if it exists further down

QUOTED_DATE_ONLY_FRONTMATTER_RE = re.compile(
    r'(?m)^[A-Za-z_][A-Za-z0-9_-]*:\s*(["\'])\d{4}-\d{2}-\d{2}\1\s*$'
)


def _resolve_article_identity(article: Dict[str, Any]) -> str:
    """Return the stable identity string used as this article's refinery_id.

    Prefers the DB primary key (``article["id"]``); every real
    collector-sourced article has one. Some legitimate non-DB inputs (the
    filesystem-fallback ingestion path in ``apps/refinery/main.py``, ad hoc
    test fixtures) have no "id" key at all — for those we fall back to the
    title, same as the historical behavior, but log so the gap is visible
    instead of silent.

    Plan 021 (rebuild the publication callback contract) persists this
    exact string into the DB row's
    ``article_metadata["publication"]["refinery_id"]`` (see
    ``ArticleRepository.mark_article_published`` / ``database.py``) and the
    frontend webhook handler matches callbacks' ``publication_ids`` against
    it — a title fallback row therefore won't correlate reliably with
    frontend publication callbacks, which is why it logs loudly.
    """
    article_pk = article.get("id")
    if article_pk not in (None, ""):
        return str(article_pk)
    logger.warning(
        "Article has no DB id; falling back to title for refinery_id "
        f"(title={article.get('title')!r}). This article won't correlate "
        "reliably with frontend publication callbacks."
    )
    return str(article.get("title", "unknown"))


class RefineryEngine:
    """
    Orchestrates the refinement pipeline:
    1. Processing articles via EditorAgent
    2. Managing File I/O for target repo
    3. Git operations (Branch, Commit, PR)
    4. Database updates
    """

    def __init__(
        self,
        db_manager: "DatabaseManager",
        git_handler: GitHubPublisher,
        editor_agent: EditorAgent,
        config: Any,
        contract_validator=None,
    ):
        self.db = db_manager
        self.config = config
        self.contract_validator = contract_validator
        from news_collector.editorial.policy import EditorialPolicy

        # Load Policy
        # Check app.editorial_mode first, fall back to root if needed (though we moved it)
        mode = getattr(self.config.app, "editorial_mode", "standard")
        self.policy = EditorialPolicy.from_mode(mode)

        # INTEGRITY CHECK
        integrity_mode = getattr(self.config.app, "policy_integrity_mode", "enforced")

        if integrity_mode == "disabled":
            logger.info(
                "⚠️ Policy Integrity Check DISABLED by configuration (Test Mode)"
            )
        else:
            try:
                import news_collector.editorial

                manifest_path = (
                    Path(news_collector.editorial.__file__).parent
                    / "policy_manifest.json"
                )

                try:
                    self.policy.verify_integrity(manifest_path)
                except Exception as e:
                    if integrity_mode == "warn":
                        logger.warning(
                            f"⚠️ Policy Integrity Check Failed (Mode: Warn): {e}"
                        )
                    else:
                        # Enforced (Default)
                        logger.critical(f"FATAL: Policy Integrity Check Failed: {e}")
                        raise e

            except Exception as e:
                # Catch-all for outer errors (import/path issues) unrelated to verification logic itself
                # unless it was the raised error from above
                if integrity_mode == "enforced":
                    logger.critical(f"FATAL: Policy Integrity System Error: {e}")
                    raise e
                logger.error(f"Policy Integrity System Error (Non-Fatal): {e}")

        logger.info(
            f"Refinery Engine initialized with Editorial Mode: {self.policy.mode.upper()}"
        )

        # Enforcement Log Path
        paths = getattr(config, "paths", None) or {}
        if isinstance(paths, dict):
            data_dir = paths.get("data_dir", "./data")
        else:
            data_dir = getattr(paths, "data_dir", "./data")
        if not isinstance(data_dir, (str, os.PathLike)):
            data_dir = "./data"
        self.data_dir = Path(data_dir)
        runtime_dir = self.data_dir / "runtime"
        runtime_dir.mkdir(parents=True, exist_ok=True)
        self.enforcement_log_path = (
            runtime_dir / "editorial_policy_enforcement_log.jsonl"
        )
        self.publication_attempts_dir = runtime_dir / "publication_attempts"
        self.publication_attempts_dir.mkdir(parents=True, exist_ok=True)
        self.image_briefs = ImageBriefStore(self.data_dir)

        self.editor = editor_agent
        self.git = git_handler

        # Auditor & Executor
        self.auditor = EditorialAuditor(self.config)

        # ThreadPool for Auditor (Non-blocking)
        from concurrent.futures import ThreadPoolExecutor

        self.executor = ThreadPoolExecutor(max_workers=1)
        self._last_audit_future: Optional[concurrent.futures.Future[Dict[str, Any]]] = (
            None
        )

        self._last_blocked_error: Dict[str, str] | None = None

        self.writer = TargetRepoWriter()
        self.identity_resolver = PublicationIdentityResolver(
            db=self.db, manifest=self.writer
        )
        self.image_handler = ArticleImageHandler(image_briefs=self.image_briefs)
        self.pr_orchestrator = PROrchestrator(
            git=self.git, db=self.db, config=self.config
        )

    def process_articles(
        self, articles: List[Dict[str, Any]], target_repo_obj: Any, target_dir: Path
    ) -> Dict[str, Any]:
        """
        Processes a batch of articles.

        Args:
            articles: List of article dictionaries.
            target_repo_obj: git.Repo object for the target repository.
            target_dir: Path to the target repository root.

        Returns:
            Summary dictionary {processed_count, errors}
        """
        processed_count = 0
        errors = []

        for article in articles:
            article_id = "unknown"
            try:
                self._last_blocked_error = None
                # Identifier
                article_id = _resolve_article_identity(article)
                logger.info(f"Refining item: {article_id}")

                if self.process_single_article(article, target_repo_obj, target_dir):
                    processed_count += 1
                elif self._last_blocked_error:
                    errors.append({"id": article_id, **self._last_blocked_error})
                else:
                    # process_single_article returned False WITHOUT raising and
                    # WITHOUT a blocked-error code — e.g. a stage like
                    # frontend_publication_validation failed closed. The
                    # attempt summary was persisted with success=False; surface
                    # the failure to the caller instead of silently reporting
                    # "0 processed = success" (found 2026-08-11: a taxonomy
                    # contract violation aborted publication but the CLI/UI
                    # reported success).
                    errors.append(
                        {
                            "id": article_id,
                            "error": (
                                "Publication pipeline failed (see attempt summary "
                                "in data/runtime/publication_attempts/)"
                            ),
                            "message": (
                                "El pipeline de publicación falló antes de crear "
                                "el PR (validación de frontend u otra etapa). "
                                "Revisa data/runtime/publication_attempts/."
                            ),
                        }
                    )

            except Exception as e:
                logger.error(f"Failed to process {article_id}: {e}")
                entry = {
                    "id": article_id,
                    "error": str(e),
                    "message": getattr(e, "public_message", str(e)),
                }
                error_code = getattr(e, "error_code", None)
                if error_code:
                    entry["error_code"] = error_code
                errors.append(entry)

        return {"processed_count": processed_count, "errors": errors}

    def process_single_article(  # noqa: C901
        self, article: Dict[str, Any], target_repo_obj: Any, target_dir: Path
    ) -> bool:
        """
        Orchestrates full cycle for one article.
        Returns True if successful (PR created), False otherwise.
        """
        article_id = _resolve_article_identity(article)
        publication_stages: list[PublicationAttemptStageResult] = []
        branch_name: str | None = None
        final_slug: str | None = None
        output_filename: str | None = None
        pr_url: str | None = None
        validation_summary_path: str | None = None

        def record_stage(name: str, success: bool, **details: Any) -> None:
            publication_stages.append(
                PublicationAttemptStageResult(
                    name=name,
                    success=success,
                    details={
                        key: value
                        for key, value in details.items()
                        if value is not None
                    },
                )
            )

        def persist_attempt(
            success: bool, failure_class: PublicationFailureClass | None = None
        ) -> None:
            self._persist_publication_attempt_summary(
                article_id=article_id,
                success=success,
                stages=publication_stages,
                output_filename=output_filename,
                final_slug=final_slug,
                branch_name=branch_name,
                pr_url=pr_url,
                validation_summary_path=validation_summary_path,
                failure_class=failure_class,
                target_repo=getattr(
                    getattr(self.config, "github", None), "target_repo_url", None
                ),
            )

        # --- S1 GUARD: Enforce Content Contract via Injected Validator ---
        if self.contract_validator:
            try:
                article = self.contract_validator(article)
            except Exception as e:
                # Requisito explícito: logger.warning(..., exc_info=True)
                # Y asegurar propagación en pruebas para caplog
                from news_collector.utils.logger import get_logger

                req_logger = get_logger().create_module_logger("RefineryEngine")
                req_logger.warning(
                    "Data Contract Validation failure: Article {article_id} rejected: {e}",
                    article_id=article_id,
                    e=e,
                    exc_info=True,
                )
                record_stage(
                    "contract_validation",
                    False,
                    error=str(e),
                )
                persist_attempt(False)
                return False

        article = self._normalize_article_payload(article)

        # --- B-01 / F-0012, F-0015: Publishing state recovery ---
        _numeric_id: int | None = None
        with contextlib.suppress(ValueError, TypeError):
            _numeric_id = int(article_id)

        if _numeric_id is not None:
            recovery_result = self.pr_orchestrator.attempt_recovery(
                numeric_id=_numeric_id,
                article_id=article_id,
                article=article,
                git_handler=self.git,
            )
            if recovery_result is not None:
                pr_url = recovery_result.pr_url
                record_stage("publishing_recovery", True, pr_url=pr_url)
                persist_attempt(True)
                return True
            # recovery_result is None → no recovery needed, continue normal flow

        # 1. Canonical Identity Check (Idempotency)
        posts_dir = target_dir / "src/content/posts"

        identity = self.identity_resolver.resolve(article_id, article, posts_dir)
        canonical_date = identity.canonical_date
        # For locked identities (P1/P2) output_filename and final_slug are already set.
        # For creation mode (P3) they remain as provisional values until after AI editing.
        final_slug = identity.final_slug if not identity.is_new else None
        output_filename = identity.output_filename if not identity.is_new else None
        # preferred_slug is used for image-asset naming; only relevant when identity is stable.
        _image_preferred_slug = identity.final_slug if not identity.is_new else None
        record_stage(
            "identity_resolved",
            True,
            canonical_date=str(canonical_date),
            is_new=identity.is_new,
            output_filename=output_filename,
        )

        # 2. AI Processing
        # We pass canonical_date to ensure the frontmatter matches our filename expectation
        logger.info(f"Processing with intended date: {canonical_date}")

        # --- IMAGE HANDLING ---
        img_resolution = self.image_handler.resolve(
            article=article,
            article_id=article_id,
            canonical_date=canonical_date,
            preferred_slug=_image_preferred_slug,
            target_dir=target_dir,
            download_fn=self._download_image,
        )
        if not img_resolution.resolved:
            record_stage("image_resolution", False)
            persist_attempt(False)
            return False
        record_stage("image_resolution", True, image_url=img_resolution.image_url)
        article["image_url"] = img_resolution.image_url
        if img_resolution.image_alt:
            article["image_alt"] = img_resolution.image_alt

        if article.get("image_url"):
            article["image_alt"] = publication_safe_image_alt(
                article.get("image_alt"), article.get("title", article_id)
            )

        # Apply Policy to Editor
        self.editor.critic_threshold = self.policy.critic_threshold
        logger.info(
            f"Enforcing Critic Threshold: {self.policy.critic_threshold} (Mode: {self.policy.mode})"
        )

        try:
            refined_content = self.editor.process_article(
                article, override_date=canonical_date, explicit_article_id=article_id
            )
        except ValueError as ve:
            error_code = getattr(ve, "error_code", None)
            if error_code:
                self._last_blocked_error = {
                    "error": str(ve),
                    "message": str(ve),
                    "error_code": error_code,
                }
                logger.warning(f"⛔ Blocked before publish ({error_code}): {ve}")
                record_stage(
                    "editor_refinement",
                    False,
                    error_code=error_code,
                    error=str(ve),
                )
                persist_attempt(False)
                return False
            if "Translation Guardrail" in str(ve):
                logger.warning(f"⛔ Blocked by Editorial Policy (Critic): {ve}")
                record_stage("editor_refinement", False, error=str(ve))
                persist_attempt(False)
                return False
            raise ve
        record_stage("editor_refinement", True)

        audit_should_run = False
        try:
            audit_should_run = self.auditor.should_run_fast(article, refined_content)
        except Exception as e:
            logger.warning(f"Auditor pre-check failed for {article_id}: {e}")

        # 3. Determine Output Filename (if not yet locked)
        if identity.is_new:
            # Creation mode: derive slug from AI-translated content and apply collision check.
            # Pass self._extract_slug so that test-level monkeypatches are respected.
            identity = self.identity_resolver.finalize_slug(
                identity,
                refined_content,
                article_id,
                posts_dir,
                extract_slug_fn=self._extract_slug,
            )
        final_slug = identity.final_slug
        output_filename = identity.output_filename
        record_stage(
            "slug_finalized",
            bool(output_filename),
            final_slug=final_slug,
            output_filename=output_filename,
        )

        # --- POLICY ENFORCEMENT: AUDITOR CHECK ---
        # OBJECTIVE: Enforce Policy BEFORE Persistence (Writing File / Manifest / Git)
        # Check cached score first.
        cached_score = self.auditor.get_cached_score(article_id)

        if not self._enforce_editorial_policy(article_id, cached_score):
            logger.warning(
                f"⛔ Article {article_id} rejected by Editorial Policy (Auditor/Strictness)."
            )
            record_stage("policy_gate", False)
            persist_attempt(False)
            return False
        record_stage("policy_gate", True)

        if self._has_quoted_date_only_frontmatter(refined_content):
            logger.error(
                "Quoted date-only frontmatter detected for article {}. Aborting before branch/commit/push.",
                article_id,
            )
            record_stage("frontmatter_guard", False, reason="quoted_date_only")
            persist_attempt(False)
            return False
        record_stage("frontmatter_guard", True)

        # Persist canonical slug AFTER policy approval (B-02 / F-0018)
        # Only needed for new articles; P1/P2 identities already have DB entries.
        if identity.is_new and final_slug:
            self.identity_resolver.register_slug(article_id, final_slug)

        # 4. Create Branch
        # Create/sync the branch before writing files so branch collisions or
        # remote sync failures do not leave uncommitted content edits behind.
        if not output_filename:
            logger.error(f"Cannot proceed without output_filename for {article_id}")
            record_stage("output_filename", False)
            persist_attempt(False)
            return False

        branch_slug = output_filename.replace(".md", "")
        expected_branch = f"content/update-{branch_slug}"

        # B-01 / F-0012: Mark as "publishing" BEFORE git operations
        if _numeric_id is not None and hasattr(self.db, "mark_article_publishing"):
            try:
                self.db.mark_article_publishing(_numeric_id, expected_branch)
                logger.info(
                    f"Marked article {article_id} as 'publishing' (branch: {expected_branch})"
                )
            except Exception as e:
                logger.error(f"Failed to mark article as publishing: {e}")

        branch_name = self.git.create_branch(
            target_repo_obj, branch_prefix="content/update", explicit_name=branch_slug
        )
        record_stage("branch_created", True, branch_name=branch_name)

        # 5. Save File
        try:
            self.writer.write_article(
                posts_dir=posts_dir,
                output_filename=output_filename,
                content=refined_content,
                article_id=article_id,
                target_dir=target_dir,
            )
        except ValueError as e:
            logger.error("🚨 S0 GUARD: {}", e)
            record_stage("file_written", False, error=str(e))
            persist_attempt(False)
            return False
        record_stage("file_written", True, output_filename=output_filename)

        package_json = target_dir / "package.json"
        if package_json.exists():
            validation_summary_path = str(
                self.publication_attempts_dir
                / f"{self._safe_publication_artifact_name(article_id)}.frontend_validation.json"
            )

            # Fast, dependency-free frontmatter check first (plan 057): the
            # full frontend build below is slow and duplicates the frontend
            # CI. Catching schema violations (e.g. sources[].date: null)
            # here aborts in milliseconds instead of after a full npm
            # ci + prettier + lint + build cycle.
            fast_ok, fast_class, fast_error = validate_post_frontmatter_fast(
                posts_dir / output_filename
            )
            if not fast_ok:
                logger.error(
                    "Fast frontmatter validation failed for {}: {}",
                    article_id,
                    fast_error,
                )
                record_stage(
                    "frontend_publication_validation",
                    False,
                    failure_class=fast_class or "taxonomy_contract_violation",
                    fast=True,
                    error=fast_error,
                )
                persist_attempt(
                    False,
                    failure_class=fast_class or "taxonomy_contract_violation",
                )
                return False

            validation_summary = run_frontend_publication_validation(
                target_dir,
                summary_output_path=Path(validation_summary_path),
                stage_fixture=False,
                post_path=posts_dir / output_filename,
                install_dependencies=not (target_dir / "node_modules").exists(),
            )
            record_stage(
                "frontend_publication_validation",
                validation_summary.success,
                failure_class=validation_summary.overall_failure_class,
                summary_path=validation_summary_path,
            )
            if not validation_summary.success:
                persist_attempt(
                    False,
                    failure_class=validation_summary.overall_failure_class,
                )
                return False
        else:
            record_stage(
                "frontend_publication_validation",
                True,
                skipped=True,
                reason="frontend_workspace_not_detected",
            )

        # (Auditor checking validation block removed from here as it is done above)

        # 6. Commit & Push
        self.git.commit_and_push(
            target_repo_obj, f"Update article: {output_filename}", branch_name
        )
        record_stage("commit_pushed", True, branch_name=branch_name)

        # 7. Create PR
        pr_result = self.pr_orchestrator.create_pr(
            article_id=article_id,
            article=article,
            branch_name=branch_name,
            output_filename=output_filename,
            git_handler=self.git,
        )
        pr_url = pr_result.pr_url

        if pr_url:
            logger.info(f"Pull Request created successfully: {pr_url}")
            record_stage("pr_created", True, pr_url=pr_url)
            numeric_id = None
            with contextlib.suppress(ValueError):
                numeric_id = int(article_id)

            source_url = article.get("url") or article.get("source_url") or ""
            if audit_should_run:
                self._record_audit_status(
                    article_numeric_id=numeric_id,
                    status="audit_pending",
                    reason="Auditor task submitted after PR creation.",
                    attempts=0,
                )
                self._schedule_optional_audit(
                    article_id=article_id,
                    article_numeric_id=numeric_id,
                    content=refined_content,
                    source_url=source_url,
                    article_data=article,
                )
            else:
                self._record_audit_status(
                    article_numeric_id=numeric_id,
                    status="audit_skipped",
                    reason="Auditor trigger conditions not met.",
                    attempts=0,
                )

            persist_attempt(True)
            return True
        else:
            logger.error("Failed to create PR.")
            record_stage("pr_created", False)
            persist_attempt(False)
            return False

    def _persist_publication_attempt_summary(
        self,
        *,
        article_id: str,
        success: bool,
        stages: list[PublicationAttemptStageResult],
        target_repo: str | None = None,
        output_filename: str | None = None,
        final_slug: str | None = None,
        branch_name: str | None = None,
        pr_url: str | None = None,
        validation_summary_path: str | None = None,
        failure_class: PublicationFailureClass | None = None,
    ) -> None:
        safe_article_id = self._safe_publication_artifact_name(article_id)

        summary = PublicationAttemptSummary(
            generated_at=datetime.now(timezone.utc).isoformat(),
            article_id=article_id,
            target_repo=target_repo,
            output_filename=output_filename,
            final_slug=final_slug,
            branch_name=branch_name,
            pr_url=pr_url,
            validation_summary_path=validation_summary_path,
            success=success,
            failure_class=failure_class,
            stages=stages,
        )

        summary_path = self.publication_attempts_dir / f"{safe_article_id}.json"
        summary_path.write_text(
            json.dumps(summary.model_dump(mode="json"), indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _safe_publication_artifact_name(article_id: str) -> str:
        safe_article_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", article_id).strip("_")
        return safe_article_id or "unknown"

    def _record_audit_status(
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
        update_status = getattr(self.db, "update_article_audit_status", None)
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

    def _schedule_optional_audit(
        self,
        *,
        article_id: str,
        article_numeric_id: int | None,
        content: str,
        source_url: str,
        article_data: Dict[str, Any],
    ) -> None:
        try:
            if self._last_audit_future and not self._last_audit_future.done():
                logger.warning(
                    f"Auditor Backpressure: Skipping audit for {article_id} (Previous task still active)"
                )
                self._record_audit_status(
                    article_numeric_id=article_numeric_id,
                    status="audit_skipped_backpressure",
                    reason="Skipped because previous audit task is still running.",
                    attempts=0,
                )
                return

            logger.info(
                f"Submitting optional auditor task for {article_id} after PR creation."
            )
            future = self.executor.submit(
                self.auditor.audit_article_sync,
                article_id=article_id,
                content=content,
                source_url=source_url,
                article_data=article_data,
            )
            self._last_audit_future = future

            def _on_done(done_future):
                try:
                    audit_result = done_future.result() or {}
                except Exception as exc:
                    message = (
                        f"Optional auditor task crashed for article {article_id}: {exc}"
                    )
                    logger.warning(message)
                    self._record_audit_status(
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

                self._record_audit_status(
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
            self._record_audit_status(
                article_numeric_id=article_numeric_id,
                status="audit_failed",
                reason=f"submission_failed: {e}",
                attempts=0,
            )

    def _extract_slug(self, content: str, fallback_id: str) -> str:
        """Extracts slug from frontmatter or generates fallback."""
        slug = None
        if "slug:" in content:
            match = re.search(r'slug:\s*"?([^"\n]+)"?', content)
            if match:
                slug = match.group(1).strip()

        if not slug and "title:" in content:
            title_match = re.search(r'title:\s*"?([^"\n]+)"?', content)
            if title_match:
                slug = title_match.group(1).strip()

        if not slug:
            slug = f"article-{fallback_id}"

        # --- NC-BE-015 S0 GUARD: Strict sanitize ---
        slug = slugify(slug, fallback=f"article-{fallback_id}")

        return slug

    def _has_quoted_date_only_frontmatter(self, content: str) -> bool:
        """
        Reject frontmatter when any key has a quoted date-only token (YYYY-MM-DD).
        Generic by key name; does not special-case `date`.
        """
        if not isinstance(content, str) or not content.startswith("---\n"):
            return False

        end_marker_idx = content.find("\n---", 4)
        if end_marker_idx == -1:
            return False

        frontmatter_block = content[4:end_marker_idx]
        return bool(QUOTED_DATE_ONLY_FRONTMATTER_RE.search(frontmatter_block))

    def _download_image(self, url: str, slug: str, target_dir: Path) -> str | None:
        """
        Downloads a remote image to the local assets directory.
        Returns the Astro-compatible local path (e.g. "~/assets/images/slug.jpg")
        or None if download fails.
        """
        url = str(url).strip()
        if not url or not url.startswith("http"):
            return None

        # Determine extension from Content-Type header (reliable) with URL heuristic fallback
        ext = None  # resolved after first request below

        # Paths
        assets_dir = target_dir / "src/assets/images"
        assets_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"Downloading image from {url}")

        from news_collector.infrastructure.requests_client import RobustRequestsClient

        try:
            with RobustRequestsClient() as client:
                response = client.get(url, timeout=15)

            # Resolve extension: Content-Type first, URL heuristic fallback
            ct = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
            ext = CT_TO_EXT.get(ct)
            if not ext:
                url_lower = url.lower().split("?")[0]
                for candidate_ext in (
                    ".png",
                    ".webp",
                    ".avif",
                    ".gif",
                    ".svg",
                    ".jpeg",
                    ".jpg",
                ):
                    if url_lower.endswith(candidate_ext):
                        ext = ".jpg" if candidate_ext == ".jpeg" else candidate_ext
                        break
                else:
                    ext = ".jpg"

            filename = f"{slug}{ext}"
            local_path = assets_dir / filename
            local_path.write_bytes(response.content)
            logger.info(
                f"Image saved: {local_path} ({len(response.content) // 1024} KB, {ct})"
            )
            return f"~/assets/images/{filename}"
        except Exception as e:
            logger.error(f"Failed to download image {url}: {e}")
            return None

    def _normalize_article_payload(self, article: Any) -> Dict[str, Any]:
        """Convert contract objects and URL-like values into plain Python primitives."""
        if hasattr(article, "model_dump"):
            article = article.model_dump(mode="python")
        if not isinstance(article, dict):
            raise TypeError("Article payload must normalize to a dictionary")

        def normalize(value: Any) -> Any:
            if hasattr(value, "model_dump"):
                return normalize(value.model_dump(mode="python"))
            if isinstance(value, dict):
                return {str(key): normalize(item) for key, item in value.items()}
            if isinstance(value, list):
                return [normalize(item) for item in value]
            if isinstance(value, tuple):
                return [normalize(item) for item in value]
            if value is None or isinstance(value, (bool, int, float, str)):
                return value
            return str(value)

        return cast(Dict[str, Any], normalize(article))

    def _enforce_editorial_policy(
        self, article_id: str, cached_score: dict | None
    ) -> bool:
        """
        Enforces editorial policy deterministically and logs result.
        Returns True if allowed, False if blocked.
        """
        decision = "allowed"
        reason = "Non-blocking check passed (Fail-Open) or Score Sufficient"

        # The auditor is configured non-blocking ([editorial_auditor]
        # blocking = false, the repo default): its score is advisory and
        # must never gate publication. The policy threshold/caveats only
        # become gates when the auditor is explicitly configured blocking
        # (2026-08-12 regression: standard-mode threshold 8.0 blocked a
        # re-selected article with a cached 6.5 advisory score, even though
        # the auditor had already been allowed to publish it).
        if not getattr(self.auditor, "blocking", False):
            decision = "allowed"
            reason = "Auditor is non-blocking (config editorial_auditor.blocking=false); score advisory only"
            self._log_enforcement_decision(article_id, cached_score, decision, reason)
            return True

        try:
            # Fail-Open if no score available (Non-Blocking Auditor)
            # Using strict usage of 'is None'
            if cached_score is None:
                decision = "allowed"
                reason = "No Auditor score available (Non-blocking default)"
                return True

            epistemic = float(cached_score.get("epistemic_rigor_score", 0.0))

            # 1. Check Threshold
            if epistemic < self.policy.auditor_threshold:
                reason = f"Auditor Score {epistemic} < Threshold {self.policy.auditor_threshold}"
                logger.warning(f"⛔ Blocked by Editorial Policy (Auditor): {reason}")
                decision = "blocked"
                return False

            # 2. Check Caveats
            if self.policy.require_caveats:
                # STRICT: Default to False (block) if key usage is missing or uncertain
                # This overrides any previous logic that defaulted to True
                has_caveats = cached_score.get("has_proper_caveats", False)
                if has_caveats is not True:  # Strict bool check
                    reason = "Caveats Required but missing/false"
                    logger.warning(
                        f"⛔ Blocked by Editorial Policy (Caveats): {reason}"
                    )
                    decision = "blocked"
                    return False

            return True

        except Exception as e:
            logger.error(f"Error enforcing policy for {article_id}: {e}")
            decision = "blocked"
            reason = f"Enforcement Error: {e}"
            return False

        finally:
            self._log_enforcement_decision(article_id, cached_score, decision, reason)

    def _log_enforcement_decision(
        self, article_id: str, score: dict | None, result: str, reason: str
    ):
        """Appends structured log of enforcement decision."""
        try:
            entry = {
                "timestamp": datetime.now().isoformat(),
                "article_id": article_id,
                "mode": self.policy.mode,
                "thresholds": {
                    "critic": self.policy.critic_threshold,
                    "auditor": self.policy.auditor_threshold,
                },
                "score": score,
                "result": result,
                "reason": reason,
                "policy_sha256": self.policy.policy_sha256,
            }

            # Atomic Append
            with open(self.enforcement_log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")

        except Exception as e:
            logger.error(f"Failed to write enforcement log: {e}")
