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

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict

from news_collector.utils.logger import get_logger

logger = get_logger().create_module_logger("PROrchestrator")

PUBLISHING_TIMEOUT_SECONDS = 3600  # 1 hour


@dataclass
class PRResult:
    """Result of PROrchestrator.create_pr() or attempt_recovery()."""
    pr_url: str | None
    recovered: bool = False


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

    def create_pr(
        self,
        *,
        article_id: str,
        article: Dict[str, Any],
        branch_name: str,
        output_filename: str,
        git_handler: Any = None,
        recovered: bool = False,
    ) -> PRResult:
        """
        Create a pull request for a published article.

        Calls git.create_pull_request and, on success, marks the article as
        published in the DB.

        Args:
            recovered: When True, the PR body notes this is a publishing recovery.

        Returns a PRResult with pr_url set if successful, or pr_url=None on failure.
        """
        git = git_handler if git_handler is not None else self._git
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
            "- Deploy to GitHub Pages"
        )

        pr_url = git.create_pull_request(
            repo_url=repo_url,
            branch_name=branch_name,
            title=f"News: {output_filename.replace('.md', '')}",
            body=pr_body,
        )

        if pr_url:
            logger.info("Pull Request created successfully: {}", pr_url)
            try:
                numeric_id = int(article_id)
                self._db.mark_article_published(numeric_id, pr_url)
            except ValueError:
                logger.warning(
                    "Could not mark non-numeric ID %s in main DB. Skipping state update.",
                    article_id,
                )

        return PRResult(pr_url=pr_url, recovered=recovered)

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

    def attempt_recovery(
        self,
        *,
        numeric_id: int,
        article_id: str,
        article: Dict[str, Any],
        git_handler: Any = None,
    ) -> PRResult | None:
        """
        B-01 / F-0012 / F-0015: If article is stuck in 'publishing' state, attempt recovery.

        Returns:
            PRResult(recovered=True)  – recovery PR created, caller should return True.
            None                      – no recovery needed, caller should continue.
        """
        get_state = getattr(self._db, "get_publishing_state", None)
        if not callable(get_state):
            return None

        publishing_info = get_state(numeric_id)
        if publishing_info is None:
            return None

        publishing_started_at = publishing_info.get("publishing_started_at")
        publishing_branch = publishing_info.get("publishing_branch")

        # Check timeout
        if publishing_started_at:
            try:
                started = datetime.fromisoformat(publishing_started_at)
                if started.tzinfo is None:
                    started = started.replace(tzinfo=timezone.utc)
                elapsed = (datetime.now(timezone.utc) - started).total_seconds()
                if elapsed > PUBLISHING_TIMEOUT_SECONDS:
                    logger.warning(
                        "Article {} stuck in 'publishing' for {:.1f}h (>{:.0f}h). "
                        "Allowing reprocessing.",
                        article_id,
                        elapsed / 3600,
                        PUBLISHING_TIMEOUT_SECONDS / 3600,
                    )
                    return None
            except (ValueError, TypeError) as e:
                logger.warning("Could not parse publishing_started_at: {}", e)

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

        try:
            result = self.create_pr(
                article_id=article_id,
                article=article,
                branch_name=publishing_branch,
                output_filename=output_filename,
                git_handler=git,
                recovered=True,
            )
        except Exception as e:
            logger.warning(
                "Publishing recovery PR creation failed for {}: {}. "
                "Article stays in 'publishing' for next retry.",
                article_id,
                e,
            )
            return None

        if result.pr_url:
            logger.info("Publishing recovery succeeded for article {}: {}", article_id, result.pr_url)
            return result

        return None
