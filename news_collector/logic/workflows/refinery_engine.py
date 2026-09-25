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
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, cast

from news_collector.components.editorial.ai_editor import EditorAgent
from news_collector.components.editorial.auditor import EditorialAuditor
from news_collector.components.publishing import GitHubPublisher
from news_collector.contracts import PublicationAttemptStageResult
from news_collector.contracts.publication_validation import PublicationFailureClass
from news_collector.editorial.grounding import (
    build_source_text,
    check_grounding,
    format_pr_section,
    repair_text_hygiene,
)
from news_collector.editorial.readability import analyze_body_readability
from news_collector.logic.workflows.audit_scheduler import AuditRequest, AuditScheduler
from news_collector.logic.workflows.image_briefs import ImageBriefStore
from news_collector.logic.workflows.image_handler import (
    ArticleImageHandler,
    publication_safe_image_alt,
)
from news_collector.logic.workflows.pr_orchestrator import PROrchestrator
from news_collector.logic.workflows.publication_attempts import (
    PublicationAttempt,
    artifact_name,
    persist_interrupted_attempt,
    persist_publication_attempt,
)
from news_collector.logic.workflows.publication_identity import (
    PublicationIdentity,
    PublicationIdentityResolver,
)
from news_collector.logic.workflows.target_repo_publication import (
    PublicationDeps,
    PublicationRequest,
    TargetRepoPublicationWorkflow,
)
from news_collector.logic.workflows.target_repo_writer import TargetRepoWriter
from news_collector.utils.logger import get_logger

if "TYPE_CHECKING":
    from news_collector.storage.database import DatabaseManager

logger = get_logger().create_module_logger("RefineryEngine")

# Removing duplicate import if it exists further down

QUOTED_DATE_ONLY_FRONTMATTER_RE = re.compile(
    r'(?m)^[A-Za-z_][A-Za-z0-9_-]*:\s*(["\'])\d{4}-\d{2}-\d{2}\1\s*$'
)

_CONTRACT_REJECTED = object()


class _PublicationRun:
    """Mutable per-article publication state for one `process_single_article`
    call (plan 060 Phase 7a).

    Replaces the closure trio (`record_stage`, `persist_attempt` and the
    identity-bearing locals) so the stage methods can share state without a
    dozen parameters. Stage order and payloads stay identical: `record_stage`
    still updates the engine's `_last_publication_stages` mirror on every call
    (plan 069 interrupted-attempt persistence), and `persist_attempt` still
    goes through the engine's compatibility delegate so test-level patches on
    either seam keep intercepting.
    """

    def __init__(self, engine: "RefineryEngine", article_id: str) -> None:
        self._engine = engine
        self.article_id = article_id
        self.stages: list[PublicationAttemptStageResult] = []
        self.numeric_id: int | None = None
        self.branch_name: str | None = None
        self.final_slug: str | None = None
        self.output_filename: str | None = None
        self.pr_url: str | None = None
        self.validation_summary_path: str | None = None

    def record_stage(self, name: str, success: bool, **details: Any) -> None:
        self.stages.append(
            PublicationAttemptStageResult(
                name=name,
                success=success,
                details={
                    key: value for key, value in details.items() if value is not None
                },
            )
        )
        self._engine._last_publication_stages = self.stages

    def persist_attempt(
        self, success: bool, failure_class: PublicationFailureClass | None = None
    ) -> None:
        self._engine._persist_publication_attempt_summary(
            article_id=self.article_id,
            success=success,
            stages=self.stages,
            output_filename=self.output_filename,
            final_slug=self.final_slug,
            branch_name=self.branch_name,
            pr_url=self.pr_url,
            validation_summary_path=self.validation_summary_path,
            failure_class=failure_class,
            target_repo=getattr(
                getattr(self._engine.config, "github", None), "target_repo_url", None
            ),
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
            logger.info("Policy Integrity Check DISABLED by configuration (Test Mode)")
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
                            f"Policy Integrity Check Failed (Mode: Warn): {e}"
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
        self.audit_scheduler = AuditScheduler(self.db)

        self._last_blocked_error: Dict[str, str] | None = None

        # Mirror of the in-flight `publication_stages` list of the article
        # currently in `process_single_article` (plan 069): lets the
        # `process_articles` except-block persist accumulated stages when an
        # unexpected exception skips every explicit `persist_attempt` path.
        self._last_publication_stages: Optional[List[PublicationAttemptStageResult]] = (
            None
        )

        self.writer = TargetRepoWriter()
        self.identity_resolver = PublicationIdentityResolver(
            db=self.db, manifest=self.writer
        )
        self.image_handler = ArticleImageHandler(image_briefs=self.image_briefs)
        self.pr_orchestrator = PROrchestrator(
            git=self.git, db=self.db, config=self.config
        )
        self.publication_workflow = TargetRepoPublicationWorkflow()

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
                self._persist_interrupted_attempt(
                    article_id, self._last_publication_stages
                )
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

    @staticmethod
    def _record_grounding_stage(
        article: Dict[str, Any], refined_content: Any, record_stage: Any
    ) -> str:
        """Advisory grounding stage: NO failure here may abort a publication.
        Returns the PR-body section for the reviewer ("" when nothing to flag).

        Any error (checker defect, stage serialization) is logged with the article
        context and preserved as a structured skipped/error stage instead.
        """
        if not isinstance(refined_content, str):
            return ""
        article_id = article.get("id")
        try:
            report = check_grounding(refined_content, build_source_text(article))
            details = report.stage_details()
            success = not report.errors
            if report.errors or report.warnings:
                logger.warning(
                    f"Grounding [{article_id}]: {len(report.errors)} errors, "
                    f"{len(report.warnings)} warnings {report.by_kind()}"
                )
            record_stage("grounding", success, **details)
            return format_pr_section(report)
        except Exception as exc:  # noqa: BLE001 - advisory stage must never block
            logger.warning(
                f"Grounding check failed for {article_id} (advisory, ignored): {exc!r}"
            )
            try:
                record_stage(
                    "grounding", True, skipped_reason="checker_error", error=repr(exc)
                )
            except Exception as stage_exc:  # noqa: BLE001 - still advisory
                logger.warning(f"Could not record grounding error stage: {stage_exc!r}")
        return ""

    def process_single_article(
        self, article: Dict[str, Any], target_repo_obj: Any, target_dir: Path
    ) -> bool:
        """
        Orchestrates full cycle for one article.
        Returns True if successful (PR created), False otherwise.
        """
        # Reset first: a raise before any stage (e.g. identity resolve)
        # must not attribute the previous article's stages to this one.
        self._last_publication_stages = None
        article_id = _resolve_article_identity(article)
        run = _PublicationRun(self, article_id)

        # --- S1 GUARD: Enforce Content Contract via Injected Validator ---
        article = self._apply_contract_guard(article, run)
        if article is _CONTRACT_REJECTED:
            return False

        article = self._normalize_article_payload(article)

        # --- B-01 / F-0012, F-0015: Publishing state recovery ---
        if self._attempt_publishing_recovery(article_id, article, run):
            return True

        # 1. Canonical Identity Check (Idempotency)
        posts_dir = target_dir / "src/content/posts"
        identity = self._resolve_identity(article_id, article, posts_dir, run)

        # 2. AI Processing
        # We pass canonical_date to ensure the frontmatter matches our filename expectation
        logger.info(f"Processing with intended date: {identity.canonical_date}")

        if not self._resolve_article_image(
            article, article_id, identity, target_dir, run
        ):
            return False

        refinement = self._refine_article(
            article, article_id, identity.canonical_date, run
        )
        if refinement is None:
            return False
        refined_content, grounding_notes = refinement
        audit_should_run = self._audit_should_run(article, refined_content, article_id)

        # 3. Determine Output Filename (if not yet locked)
        identity = self._finalize_output_identity(
            article_id, refined_content, identity, posts_dir, run
        )

        if not self._enforce_publication_gates(
            article_id, refined_content, identity, run
        ):
            return False

        return self._publish_to_target_repo(
            target_repo_obj=target_repo_obj,
            target_dir=target_dir,
            article=article,
            refined_content=refined_content,
            grounding_notes=grounding_notes,
            audit_should_run=audit_should_run,
            run=run,
        )

    def _audit_should_run(
        self, article: Dict[str, Any], refined_content: str, article_id: str
    ) -> bool:
        try:
            return bool(self.auditor.should_run_fast(article, refined_content))
        except Exception as e:
            logger.warning(f"Auditor pre-check failed for {article_id}: {e}")
            return False

    def _apply_contract_guard(self, article: Any, run: "_PublicationRun") -> Any:
        """S1 guard: enforce the content contract via the injected validator.

        Returns the validated article, or the `_CONTRACT_REJECTED` sentinel
        after recording + persisting the failed attempt.
        """
        if not self.contract_validator:
            return article
        try:
            return self.contract_validator(article)
        except Exception as e:
            # Requisito explícito: logger.warning(..., exc_info=True)
            # Y asegurar propagación en pruebas para caplog
            from news_collector.utils.logger import get_logger

            req_logger = get_logger().create_module_logger("RefineryEngine")
            req_logger.warning(
                "Data Contract Validation failure: Article {article_id} rejected: {e}",
                article_id=run.article_id,
                e=e,
                exc_info=True,
            )
            run.record_stage(
                "contract_validation",
                False,
                error=str(e),
            )
            run.persist_attempt(False)
            return _CONTRACT_REJECTED

    def _attempt_publishing_recovery(
        self, article_id: str, article: Dict[str, Any], run: "_PublicationRun"
    ) -> bool:
        """B-01 / F-0012, F-0015: recover an article stuck in `publishing`.

        Returns True when recovery completed the publication (caller returns
        immediately); False means "no recovery needed, continue normal flow".
        """
        run.numeric_id = None
        with contextlib.suppress(ValueError, TypeError):
            run.numeric_id = int(article_id)

        if run.numeric_id is not None:
            recovery_result = self.pr_orchestrator.attempt_recovery(
                numeric_id=run.numeric_id,
                article_id=article_id,
                article=article,
                git_handler=self.git,
            )
            if recovery_result is not None:
                run.pr_url = recovery_result.pr_url
                run.record_stage("publishing_recovery", True, pr_url=run.pr_url)
                run.persist_attempt(True)
                return True
            # recovery_result is None → no recovery needed, continue normal flow
        return False

    def _resolve_identity(
        self,
        article_id: str,
        article: Dict[str, Any],
        posts_dir: Path,
        run: "_PublicationRun",
    ) -> PublicationIdentity:
        identity = self.identity_resolver.resolve(article_id, article, posts_dir)
        # For locked identities (P1/P2) output_filename and final_slug are already set.
        # For creation mode (P3) they remain as provisional values until after AI editing.
        run.final_slug = identity.final_slug if not identity.is_new else None
        run.output_filename = identity.output_filename if not identity.is_new else None
        run.record_stage(
            "identity_resolved",
            True,
            canonical_date=str(identity.canonical_date),
            is_new=identity.is_new,
            output_filename=run.output_filename,
        )
        return identity

    def _finalize_output_identity(
        self,
        article_id: str,
        refined_content: str,
        identity: PublicationIdentity,
        posts_dir: Path,
        run: "_PublicationRun",
    ) -> PublicationIdentity:
        """Lock the creation-mode slug from the AI-translated content and
        record the `slug_finalized` stage."""
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
        run.final_slug = identity.final_slug
        run.output_filename = identity.output_filename
        run.record_stage(
            "slug_finalized",
            bool(run.output_filename),
            final_slug=run.final_slug,
            output_filename=run.output_filename,
        )
        return identity

    def _resolve_article_image(
        self,
        article: Dict[str, Any],
        article_id: str,
        identity: PublicationIdentity,
        target_dir: Path,
        run: "_PublicationRun",
    ) -> bool:
        # preferred_slug is used for image-asset naming; only relevant when identity is stable.
        image_preferred_slug = identity.final_slug if not identity.is_new else None
        img_resolution = self.image_handler.resolve(
            article=article,
            article_id=article_id,
            canonical_date=identity.canonical_date,
            preferred_slug=image_preferred_slug,
            target_dir=target_dir,
            download_fn=self._download_image,
        )
        if not img_resolution.resolved:
            run.record_stage("image_resolution", False)
            if img_resolution.message:
                self._last_blocked_error = {
                    "error": img_resolution.message,
                    "message": img_resolution.message,
                }
                logger.warning(f"Blocked before publish: {img_resolution.message}")
            run.persist_attempt(False)
            return False
        run.record_stage("image_resolution", True, image_url=img_resolution.image_url)
        article["image_url"] = img_resolution.image_url
        if img_resolution.image_alt:
            article["image_alt"] = img_resolution.image_alt

        if article.get("image_url"):
            article["image_alt"] = publication_safe_image_alt(
                article.get("image_alt"), article.get("title", article_id)
            )
        return True

    def _refine_article(
        self,
        article: Dict[str, Any],
        article_id: str,
        canonical_date: str,
        run: "_PublicationRun",
    ) -> tuple[str, str] | None:
        """Run the editor plus the advisory snapshots.

        Returns `(refined_content, grounding_notes)`, or None when editorial
        policy blocks the article (the blocked attempt is persisted).
        """
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
                logger.warning(f"Blocked before publish ({error_code}): {ve}")
                run.record_stage(
                    "editor_refinement",
                    False,
                    error_code=error_code,
                    error=str(ve),
                )
                run.persist_attempt(False)
                return None
            if "Translation Guardrail" in str(ve):
                logger.warning(f"Blocked by Editorial Policy (Critic): {ve}")
                run.record_stage("editor_refinement", False, error=str(ve))
                run.persist_attempt(False)
                return None
            raise ve
        run.record_stage("editor_refinement", True)
        return self._record_advisory_stages(article, refined_content, run)

    def _record_advisory_stages(
        self,
        article: Dict[str, Any],
        refined_content: str,
        run: "_PublicationRun",
    ) -> tuple[str, str]:
        """Hygiene repair, critic verdict, grounding and readability.

        All advisory: none of these may block publication. Returns the
        repaired content and the grounding notes for the PR body.
        """
        # Deterministic typography repair over the whole file (frontmatter and
        # body): the model habitually emits U+202F before units and U+2011 in
        # compounds. Pure string replacement; recorded only when it changed
        # something so clean runs stay quiet.
        if isinstance(refined_content, str):
            refined_content, repaired_chars = repair_text_hygiene(refined_content)
            if repaired_chars:
                logger.info(f"Text hygiene: repaired {repaired_chars} special chars.")
                run.record_stage("text_hygiene", True, repaired_chars=repaired_chars)

        # Editorial-critic verdict snapshot (plan 076): the editor stashes
        # its last verdict on `last_critic_verdict`; mock editors lack the
        # attribute and are skipped via getattr. Stage success mirrors the
        # verdict — a published-with-caveat article shows a red critic row.
        critic_verdict = getattr(self.editor, "last_critic_verdict", None)
        if isinstance(critic_verdict, dict) and isinstance(
            critic_verdict.get("average"), (int, float)
        ):
            run.record_stage(
                "editorial_critic",
                bool(critic_verdict.get("approved", False)),
                average=float(critic_verdict["average"]),
            )

        # Editorial grounding (advisory, never blocks): compares figures, vague
        # quantities and scope claims of the refined file with the source text the
        # editor wrote from. Findings persist in the attempt summary for review.
        grounding_notes = self._record_grounding_stage(
            article, refined_content, run.record_stage
        )

        # Deterministic audience-readability snapshot (plan 065): pure
        # computation over the refined body, advisory only — it never blocks.
        # The stage persists in the attempt summary (visible via the publish
        # status API) so editors can track legibility per article.
        readability = analyze_body_readability(refined_content)
        logger.info(
            f"Readability: IFSZ={readability.ifsz} ({readability.grade}), "
            f"suitability={readability.suitability} over "
            f"{readability.words} words / {readability.sentences} sentences."
        )
        run.record_stage("readability", True, **readability.stage_details())

        return refined_content, grounding_notes

    def _enforce_publication_gates(
        self,
        article_id: str,
        refined_content: str,
        identity: PublicationIdentity,
        run: "_PublicationRun",
    ) -> bool:
        # --- POLICY ENFORCEMENT: AUDITOR CHECK ---
        # OBJECTIVE: Enforce Policy BEFORE Persistence (Writing File / Manifest / Git)
        # Check cached score first.
        cached_score = self.auditor.get_cached_score(article_id)

        if not self._enforce_editorial_policy(article_id, cached_score):
            logger.warning(
                f"Article {article_id} rejected by Editorial Policy (Auditor/Strictness)."
            )
            run.record_stage("policy_gate", False)
            run.persist_attempt(False)
            return False
        run.record_stage("policy_gate", True)

        if self._has_quoted_date_only_frontmatter(refined_content):
            logger.error(
                "Quoted date-only frontmatter detected for article {}. Aborting before branch/commit/push.",
                article_id,
            )
            run.record_stage("frontmatter_guard", False, reason="quoted_date_only")
            run.persist_attempt(False)
            return False
        run.record_stage("frontmatter_guard", True)

        # Persist canonical slug AFTER policy approval (B-02 / F-0018)
        # Only needed for new articles; P1/P2 identities already have DB entries.
        if identity.is_new and run.final_slug:
            self.identity_resolver.register_slug(article_id, run.final_slug)
        return True

    def _publish_to_target_repo(
        self,
        *,
        target_repo_obj: Any,
        target_dir: Path,
        article: Dict[str, Any],
        refined_content: str,
        grounding_notes: str,
        audit_should_run: bool,
        run: "_PublicationRun",
    ) -> bool:
        """Delegate the target-repo stages to TargetRepoPublicationWorkflow
        (plan 060 Phase 7b), then keep the engine-owned side effects — audit
        scheduling and attempt persistence — in the historical order."""
        outcome = self.publication_workflow.publish(
            PublicationRequest(
                article=article,
                article_id=run.article_id,
                numeric_id=run.numeric_id,
                output_filename=run.output_filename,
                refined_content=refined_content,
                grounding_notes=grounding_notes,
                target_repo_obj=target_repo_obj,
                target_dir=target_dir,
                attempts_dir=self.publication_attempts_dir,
            ),
            PublicationDeps(
                writer=self.writer,
                git=self.git,
                pr_orchestrator=self.pr_orchestrator,
                db=self.db,
            ),
            record_stage=run.record_stage,
        )
        run.branch_name = outcome.branch_name
        run.pr_url = outcome.pr_url
        run.validation_summary_path = outcome.validation_summary_path
        if not outcome.success:
            run.persist_attempt(False, failure_class=outcome.failure_class)
            return False
        self._schedule_or_skip_audit(article, refined_content, audit_should_run, run)
        run.persist_attempt(True)
        return True

    def _schedule_or_skip_audit(
        self,
        article: Dict[str, Any],
        refined_content: str,
        audit_should_run: bool,
        run: "_PublicationRun",
    ) -> None:
        source_url = article.get("url") or article.get("source_url") or ""
        if audit_should_run:
            self._record_audit_status(
                article_numeric_id=run.numeric_id,
                status="audit_pending",
                reason="Auditor task submitted after PR creation.",
                attempts=0,
            )
            self._schedule_optional_audit(
                article_id=run.article_id,
                article_numeric_id=run.numeric_id,
                content=refined_content,
                source_url=source_url,
                article_data=article,
            )
        else:
            self._record_audit_status(
                article_numeric_id=run.numeric_id,
                status="audit_skipped",
                reason="Auditor trigger conditions not met.",
                attempts=0,
            )

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
        """Compatibility delegate (plan 060 Phase 7a): PublicationAttempts owns
        the artifact format. Reads `self.publication_attempts_dir` at call time
        so per-instance redirection (tests, config) keeps working."""
        persist_publication_attempt(
            self.publication_attempts_dir,
            PublicationAttempt(
                article_id=article_id,
                success=success,
                stages=stages,
                target_repo=target_repo,
                output_filename=output_filename,
                final_slug=final_slug,
                branch_name=branch_name,
                pr_url=pr_url,
                validation_summary_path=validation_summary_path,
                failure_class=failure_class,
            ),
        )

    @staticmethod
    def _safe_publication_artifact_name(article_id: str) -> str:
        """Compatibility delegate (plan 060 Phase 7a): kept so existing test
        and harness call sites keep resolving `RefineryEngine.<name>`."""
        return artifact_name(article_id)

    def _persist_interrupted_attempt(
        self,
        article_id: str,
        stages: Optional[List[PublicationAttemptStageResult]],
    ) -> None:
        """Compatibility delegate (plan 060 Phase 7a)."""
        persist_interrupted_attempt(self.publication_attempts_dir, article_id, stages)

    @property
    def _last_audit_future(self) -> Optional[concurrent.futures.Future]:
        """Compatibility shim (plan 060 Phase 7a): backpressure state lives on
        AuditScheduler; existing callers/tests still read/write it here."""
        return self.audit_scheduler.last_future

    @_last_audit_future.setter
    def _last_audit_future(self, value: Optional[concurrent.futures.Future]) -> None:
        self.audit_scheduler.last_future = value

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
        """Compatibility delegate (plan 060 Phase 7a)."""
        self.audit_scheduler.record_status(
            article_numeric_id,
            status,
            reason,
            attempts,
            timeout_seconds=timeout_seconds,
            model=model,
            endpoint=endpoint,
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
        """Compatibility delegate (plan 060 Phase 7a)."""
        self.audit_scheduler.schedule(
            auditor=self.auditor,
            executor=self.executor,
            # Late-bound so test-level patch.object(engine,
            # "_record_audit_status") still intercepts callback-time writes.
            status_recorder=lambda *args, **kwargs: self._record_audit_status(
                *args, **kwargs
            ),
            request=AuditRequest(
                article_id=article_id,
                article_numeric_id=article_numeric_id,
                content=content,
                source_url=source_url,
                article_data=article_data,
            ),
        )

    def _extract_slug(self, content: str, fallback_id: str) -> str:
        """Extract slug from frontmatter or generate fallback.

        Delegates to PublicationIdentityResolver.extract_slug — the single
        slug-extraction implementation (LAW-B5). All slug-extraction fixes
        land there. Kept as a thin wrapper so the finalize_slug
        extract_slug_fn hook and test-level monkeypatches keep working.
        """
        return PublicationIdentityResolver.extract_slug(content, fallback_id)

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

        Compatibility delegate (plan 093): ArticleImageHandler.download owns
        all download policy (timeout, retries, extension map). Kept so the
        image_handler.resolve download_fn hook and test-level monkeypatches
        keep working.
        """
        return self.image_handler.download(url, slug, target_dir)

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
                logger.warning(f"Blocked by Editorial Policy (Auditor): {reason}")
                decision = "blocked"
                return False

            # 2. Check Caveats
            if self.policy.require_caveats:
                # STRICT: Default to False (block) if key usage is missing or uncertain
                # This overrides any previous logic that defaulted to True
                has_caveats = cached_score.get("has_proper_caveats", False)
                if has_caveats is not True:  # Strict bool check
                    reason = "Caveats Required but missing/false"
                    logger.warning(f"Blocked by Editorial Policy (Caveats): {reason}")
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
