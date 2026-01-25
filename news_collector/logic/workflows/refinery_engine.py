import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from news_collector.components.editorial.ai_editor import EditorAgent
from news_collector.components.publishing import GitHubPublisher

if "TYPE_CHECKING":
    from news_collector.storage.database import DatabaseManager

logger = logging.getLogger("RefineryEngine")


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
    ):
        self.db = db_manager
        self.git = git_handler
        self.editor = editor_agent
        self.config = config

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
            try:
                # Identifier
                article_id = str(article.get("id", article.get("title")))
                logger.info(f"Refining item: {article_id}")

                if self.process_single_article(article, target_repo_obj, target_dir):
                    processed_count += 1

            except Exception as e:
                logger.error(f"Failed to process {article_id}: {e}")
                errors.append({"id": article_id, "error": str(e)})

        return {"processed_count": processed_count, "errors": errors}

    def process_single_article(  # noqa: C901
        self, article: Dict[str, Any], target_repo_obj: Any, target_dir: Path
    ) -> bool:
        """
        Orchestrates full cycle for one article.
        Returns True if successful (PR created), False otherwise.
        """
        article_id = str(article.get("id", article.get("title")))

        # 1. Canonical Identity Check (Idempotency)
        # Check if this article already exists in the repo to preserve its URL/Date
        posts_dir = target_dir / "src/content/posts"
        existing_file = self._find_existing_file(posts_dir, article_id)

        canonical_date = None
        output_filename = None

        if existing_file:
            # Preservation Mode: Use existing filename and date
            logger.info(
                f"♻️ Idempotency: Found existing publication {existing_file.name}"
            )
            output_filename = existing_file.name
            # Extract date from filename (YYYY-MM-DD-...)
            match = re.match(r"^(\d{4}-\d{2}-\d{2})-", output_filename)
            if match:
                canonical_date = match.group(1)
            else:
                # Fallback if filename format is weird
                canonical_date = datetime.now().strftime("%Y-%m-%d")
        else:
            # Creation Mode: Derive date from source or current time
            # Ideally use source published date to be deterministic regardless of partial re-runs
            src_date = article.get("published_date")
            if src_date:
                # Try to parse source date
                try:
                    # Simple heuristic for now, assuming ISO or common format.
                    # If it's a datetime object:
                    if isinstance(src_date, datetime):
                        canonical_date = src_date.strftime("%Y-%m-%d")
                    else:
                        # Take first 10 chars if looks like ISO YYYY-MM-DD
                        s_date = str(src_date).strip()
                        if re.match(r"^\d{4}-\d{2}-\d{2}", s_date):
                            canonical_date = s_date[:10]
                except Exception:  # noqa: S110
                    pass

            if not canonical_date:
                canonical_date = datetime.now().strftime("%Y-%m-%d")

        # 2. AI Processing (Pass canonical date)
        logger.info(f"Processing with canonical date: {canonical_date}")
        refined_content = self.editor.process_article(
            article, override_date=canonical_date
        )

        # 3. Determine Output Filename (if not preserved)
        if not output_filename:
            slug = self._extract_slug(refined_content, article_id)
            output_filename = f"{canonical_date}-{slug}.md"

        # 4. Save File
        posts_dir.mkdir(parents=True, exist_ok=True)
        target_file_path = posts_dir / output_filename

        target_file_path.write_text(refined_content, encoding="utf-8")
        logger.info(f"Written content to {target_file_path}")

        # 5. Create Branch
        # Use a deterministic branch name based on ID or filename to allow updates to same PR
        branch_slug = output_filename.replace(".md", "")
        branch_name = self.git.create_branch(
            target_repo_obj, branch_prefix="content/update", explicit_name=branch_slug
        )

        # 6. Commit & Push
        self.git.commit_and_push(
            target_repo_obj, f"Update article: {output_filename}", branch_name
        )

        # 7. Create PR
        pr_url = self.git.create_pull_request(
            repo_url=self.config.target_repo_url,
            branch_name=branch_name,
            title=f"News: {output_filename.replace('.md', '')}",
            body=f"Automated submission for {article_id}.\n\nProcessed by Noticiencias Refinery.",
        )

        if pr_url:
            logger.info(f"Pull Request created successfully: {pr_url}")
            # Mark processed in Main DB
            try:
                numeric_id = int(article_id)
                self.db.mark_article_published(numeric_id, pr_url)
            except ValueError:
                logger.warning(
                    f"Could not mark non-numeric ID {article_id} in main DB. Skipping state update."
                )

            return True
        else:
            logger.error("Failed to create PR.")
            return False

    def _find_existing_file(self, posts_dir: Path, article_id: str) -> Path | None:
        """Scans the posts directory for a file containing the given refinery_id."""
        if not posts_dir.exists():
            return None

        # Optimization: Check if we have a map? No, simple scan for now.
        # 1. Try strict filename match if we knew the slug? No, slug changes.
        # 2. Grep content.

        # Check most recent files first?
        # Or search all.
        try:
            for file_path in posts_dir.glob("*.md"):
                try:
                    # Quick check: read first 50 lines (Frontmatter)
                    # We assume refinery_id is in frontmatter
                    content_head = []
                    with open(file_path, "r") as f:
                        for _ in range(50):
                            line = f.readline()
                            if not line:
                                break
                            content_head.append(line)

                    full_head = "".join(content_head)
                    if f'refinery_id: "{article_id}"' in full_head:
                        return file_path
                except Exception:  # noqa: S112
                    continue
        except Exception as e:
            logger.error(f"Error scanning for existing files: {e}")

        return None

    def _extract_slug(self, content: str, fallback_id: str) -> str:
        """Extracts slug from frontmatter or generates fallback."""
        slug = f"article-{fallback_id}"
        if "slug:" in content:
            match = re.search(r'slug:\s*"?([^"\n]+)"?', content)
            if match:
                slug = match.group(1).strip()
        return slug
