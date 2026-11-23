"""
Module role: Manages GitHub PR creation and publishing-state recovery.

Owns:
- create_pr: builds PR body, calls git.create_pull_request, marks article published
- resolve_repo_url: extracts target_repo_url from various config shapes
- attempt_recovery: detects articles stuck in "publishing" state and creates recovery PRs

Does NOT own:
- Branch creation or git commit/push (RefineryEngine orchestrates git ops directly)
- File writes
- Canonical identity
- Image handling
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from news_collector.utils.logger import get_logger

logger = get_logger().create_module_logger("PROrchestrator")

PUBLISHING_TIMEOUT_SECONDS = 3600  # 1 hour


@dataclass
class PRResult:
    """Result of PROrchestrator.create_pr() or attempt_recovery()."""

    pr_url: str | None
    recovered: bool = False
    recovery_pending: bool = False


class PROrchestrator:
    """
    Manages GitHub pull-request creation and publishing-state recovery.

    Instantiate once per RefineryEngine.
    """

    def __init__(self, git: Any, db: Any, config: Any) -> None:
        self._git = git
        self._db = db
        self._config = config

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def ensure_draft_branch(self, branch_name: str, *, git_handler: Any = None) -> None:
        """Refuse changing an already ready article PR before any remote push."""
        repo_url = self.resolve_repo_url()
        if not repo_url:
            raise ValueError("Missing repository URL for article review preflight")
        git = git_handler if git_handler is not None else self._git
        git.ensure_pull_request_draft(repo_url, branch_name)

    def create_pr(
        self,
        *,
        article_id: str,
        article: Dict[str, Any],
        branch_name: str,
        output_filename: str,
        git_handler: Any = None,
        recovered: bool = False,
        adopted_recovery: bool = False,
        review_notes: str = "",
        publication_attempt_id: str | None = None,
        content_sha256: str | None = None,
    ) -> PRResult:
        """
        Create a pull request for a published article.

        Calls git.create_pull_request and, on success, marks the article as
        published in the DB.

        Args:
            recovered: When True, the PR body notes this is a publishing recovery.
            review_notes: Optional Markdown appended to the PR body (advisory
                findings for the human reviewer).

        Returns a PRResult with pr_url set if successful, or pr_url=None on failure.
        """
        git = git_handler if git_handler is not None else self._git
        try:
            numeric_id = int(article_id)
        except (TypeError, ValueError) as exc:
            logger.error(
                "Refusing to create PR for non-numeric article id {}: "
                "no DB row exists to correlate the publication with.",
                article_id,
            )
            raise AttributeError(
                f"Invalid article identity for publication: {article_id!r} "
                "is not a numeric DB id; refusing to create an untracked PR."
            ) from exc
        repo_url = self.resolve_repo_url()
        if not repo_url:
            raise AttributeError(
                "Invalid configuration: missing github.target_repo_url"
            )

        source_id = str(article.get("source_id", "")).strip() or "unknown"
        source_name = str(article.get("source_name", "")).strip() or "unknown"
        refinery_note = (
            "Processed by Noticiencias Refinery (recovered from publishing state)."
            if recovered
            else "Processed by Noticiencias Refinery."
        )
        pr_body = (
            f"Automated submission for {article_id}.\n\n"
            f"Source ID: {source_id}\n"
            f"Source Name: {source_name}\n\n"
            f"{refinery_note}\n\n"
            "Required frontend gates before merge/publication:\n"
            "- Content Guard\n"
            "- Deploy to GitHub Pages\n\n"
            "## Final human editorial review — PENDING\n\n"
            "This automated article submission starts as a draft. No human approval is implied.\n"
            "- [ ] Verify headline, body and metadata against available source evidence.\n"
            "- [ ] Resolve material unsupported claims, close paraphrase and unverified checks.\n"
            "- [ ] Confirm the actual added value and meaningful source independence.\n"
            "- [ ] Verify image provenance, relevance, labels and limitations.\n"
            "- [ ] Approve the final commit; changes to content/evidence require renewed review.\n\n"
            f"Final content SHA-256: `{content_sha256 or 'unavailable — review pending'}`\n"
            f"Source URL: {article.get('url') or article.get('source_url') or 'unavailable'}\n"
            "Image provenance (not inferred): "
            f"origin={article.get('image_origin') or 'unknown'}; "
            f"credit={article.get('image_credit') or 'unknown'}; "
            f"URL={article.get('image_url') or article.get('image') or 'unknown'}\n"
            "GitHub protected review requirements are an operator setting; this checklist "
            "does not enforce or attest a review."
        )
        if review_notes.strip():
            pr_body += f"\n\n{review_notes.strip()}"

        if adopted_recovery:
            return self._complete_adopted_recovery(
                git,
                numeric_id,
                repo_url,
                branch_name,
                output_filename,
                pr_body,
                (publication_attempt_id, content_sha256),
            )

        pr_url = git.create_pull_request(
            repo_url=repo_url,
            branch_name=branch_name,
            title=f"News: {output_filename.replace('.md', '')}",
            body=pr_body,
            draft=True,
        )

        if pr_url:
            logger.info("Pull Request created successfully: {}", pr_url)
            # article_id here is the same value refinery_engine's
            # _resolve_article_identity() writes into the committed
            # post's `refinery_id` frontmatter field (in the normal,
            # DB-id case they're the same string) — persisting it lets
            # webhook_handler match this exact publication attempt.
            # Non-numeric ids are rejected at the top of this method, so
            # the int() conversion there guarantees numeric_id is valid here.
            self._db.mark_article_published(
                numeric_id,
                pr_url,
                article_id,
                publication_attempt_id=publication_attempt_id,
                content_sha256=content_sha256,
            )

        return PRResult(pr_url=pr_url, recovered=recovered)

    def _complete_adopted_recovery(
        self,
        git: Any,
        numeric_id: int,
        repo_url: str,
        branch: str,
        filename: str,
        body: str,
        correlation: tuple[str | None, str | None],
    ) -> PRResult:
        token, digest = correlation
        if not token or not digest:
            return PRResult(None, recovery_pending=True)
        pr_url = None
        try:
            pr_url = git.get_or_create_recovery_pr(
                repo_url=repo_url,
                branch_name=branch,
                title=f"News: {filename.removesuffix('.md')}",
                body=body,
                output_filename=filename,
                content_sha256=digest,
            )
            if pr_url and self._db.lifecycle.finish_legacy_recovery(
                numeric_id, token, pr_url
            ):
                return PRResult(pr_url, recovered=True)
        except Exception as exc:
            logger.warning(
                "Recovery for article {} remains pending ({})",
                numeric_id,
                type(exc).__name__,
            )
        return PRResult(pr_url, recovery_pending=True)

    def resolve_repo_url(self) -> str | None:
        """
        Extract target_repo_url from config.

        Supports:
        - config.github.target_repo_url  (object attribute)
        - config.github["target_repo_url"]  (dict)
        - config.target_repo_url  (legacy flat attribute)
        - config["target_repo_url"]  (legacy flat dict)
        """
        github_cfg = getattr(self._config, "github", None)
        if github_cfg:
            repo_url = getattr(github_cfg, "target_repo_url", None) or (
                github_cfg.get("target_repo_url")
                if isinstance(github_cfg, dict)
                else None
            )
            if repo_url:
                return str(repo_url)

        repo_url = getattr(self._config, "target_repo_url", None)
        if repo_url is None and isinstance(self._config, dict):
            repo_url = self._config.get("target_repo_url")
        return str(repo_url) if repo_url is not None else None

    @staticmethod
    def _recovery_correlation(
        *,
        article_id: str,
        target_dir: Path | None,
        output_filename: str,
    ) -> str | None:
        """Bind a recovered PR to its exact artifact and workflow attempt."""
        if target_dir is None:
            logger.warning(
                "Cannot recover publication for article {} without its target directory; "
                "refusing an uncorrelated PR.",
                article_id,
            )
            return None
        artifact_path = target_dir / "src/content/posts" / output_filename
        try:
            content_sha256 = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
        except OSError as exc:
            logger.warning(
                "Cannot fingerprint recovery artifact for article {}: {}; "
                "refusing an uncorrelated PR.",
                article_id,
                exc,
            )
            return None
        return content_sha256

    @staticmethod
    def _recovery_timed_out(publishing_started_at: str | None, article_id: str) -> bool:
        if not publishing_started_at:
            return False
        try:
            started = datetime.fromisoformat(publishing_started_at)
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
            elapsed = (datetime.now(timezone.utc) - started).total_seconds()
        except (ValueError, TypeError) as exc:
            logger.warning("Could not parse publishing_started_at: {}", exc)
            return False
        if elapsed > PUBLISHING_TIMEOUT_SECONDS:
            logger.warning(
                "Article {} stuck in 'publishing' for {:.1f}h (>{:.0f}h). "
                "Allowing reprocessing.",
                article_id,
                elapsed / 3600,
                PUBLISHING_TIMEOUT_SECONDS / 3600,
            )
            return True
        return False

    def attempt_recovery(
        self,
        *,
        numeric_id: int,
        article_id: str,
        article: Dict[str, Any],
        git_handler: Any = None,
        target_dir: Path | None = None,
    ) -> PRResult | None:
        """
        B-01 / F-0012 / F-0015: If article is stuck in 'publishing' state, attempt recovery.

        Returns:
            PRResult – recovered or pending, caller stops normal processing.
            None                      – no recovery needed, caller should continue.
        """
        get_state = getattr(self._db, "get_publishing_state", None)
        if not callable(get_state):
            return None

        publishing_info = get_state(numeric_id)
        if not isinstance(publishing_info, dict):
            return None

        publishing_started_at = publishing_info.get("publishing_started_at")
        publishing_branch = publishing_info.get("publishing_branch")

        token = publishing_info.get("publication_attempt_id")
        stored_digest = publishing_info.get("legacy_recovery_sha256")
        already_adopted = bool(stored_digest)
        adopted_recovery = not token or already_adopted
        if not adopted_recovery and self._recovery_timed_out(
            publishing_started_at, article_id
        ):
            return None

        if not publishing_branch:
            logger.warning(
                "Article {} in 'publishing' state but no branch info. "
                "Allowing reprocessing.",
                article_id,
            )
            return None

        logger.info(
            "Attempting publishing recovery for article {} (branch: {})",
            article_id,
            publishing_branch,
        )

        git = git_handler if git_handler is not None else self._git
        slug = publishing_branch.replace("content/update-", "", 1)
        output_filename = f"{slug}.md"
        content_sha256 = stored_digest or self._recovery_correlation(
            article_id=article_id,
            target_dir=target_dir,
            output_filename=output_filename,
        )
        if content_sha256 is None:
            return PRResult(None, recovery_pending=True) if already_adopted else None

        try:
            if adopted_recovery:
                token = self._db.lifecycle.adopt_legacy_recovery(
                    numeric_id, publishing_branch, content_sha256, publishing_started_at
                )
                if not token:
                    return PRResult(None, recovery_pending=True)
            result = self.create_pr(
                article_id=article_id,
                article=article,
                branch_name=publishing_branch,
                output_filename=output_filename,
                git_handler=git,
                recovered=True,
                publication_attempt_id=token,
                content_sha256=content_sha256,
                adopted_recovery=adopted_recovery,
            )
        except Exception as e:
            logger.warning(
                "Publishing recovery PR creation failed for {}: {}. "
                "Article stays in 'publishing' for next retry.",
                article_id,
                e,
            )
            return PRResult(None, recovery_pending=True) if adopted_recovery else None

        return result if result.recovery_pending or result.pr_url else None
