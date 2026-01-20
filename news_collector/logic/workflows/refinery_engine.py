
import logging
import re
import uuid
import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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
        self, 
        articles: List[Dict[str, Any]], 
        target_repo_obj: Any,
        target_dir: Path
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
                
        return {
            "processed_count": processed_count,
            "errors": errors
        }

    def process_single_article(
        self, 
        article: Dict[str, Any], 
        target_repo_obj: Any, 
        target_dir: Path
    ) -> bool:
        """
        Orchestrates full cycle for one article.
        Returns True if successful (PR created), False otherwise.
        """
        article_id = str(article.get("id", article.get("title")))
        file_name_marker = f"{article_id}.md" 

        # 1. AI Processing
        refined_content = self.editor.process_article(article)
        
        # 2. Determine Output Metadata
        date_str = datetime.now().strftime("%Y-%m-%d")
        slug = self._extract_slug(refined_content, article_id)
        output_filename = f"{date_str}-{slug}.md"
        
        # 3. Save File
        posts_path = target_dir / "src/content/posts"
        posts_path.mkdir(parents=True, exist_ok=True)
        target_file_path = posts_path / output_filename
        
        target_file_path.write_text(refined_content, encoding="utf-8")
        logger.info(f"Written content to {target_file_path}")

        # 4. Create Branch
        # Use a deterministic branch name
        branch_name = self.git.create_branch(
            target_repo_obj, 
            branch_prefix="content/add",
            explicit_name=slug
        )

        # 5. Commit & Push
        self.git.commit_and_push(
            target_repo_obj, 
            f"Add article: {output_filename}", 
            branch_name
        )
        
        # 6. Create PR
        pr_url = self.git.create_pull_request(
            repo_url=self.config.target_repo_url,
            branch_name=branch_name,
            title=f"News: {date_str} - {slug}",
            body=f"Automated submission for {article_id}.\n\nProcessed by Noticiencias Refinery."
        )
        
        if pr_url:
            logger.info(f"Pull Request created successfully: {pr_url}")
            # Mark processed in Main DB
            # We try to convert article_id to int, assuming main DB uses int PKs
            try:
                numeric_id = int(article_id)
                self.db.mark_article_published(numeric_id, pr_url)
            except ValueError:
                # If we are somehow using string IDs (legacy), we might need a fallback or logging
                logger.warning(f"Could not mark non-numeric ID {article_id} in main DB. Skipping state update.")
            
            return True
        else:
            logger.error("Failed to create PR.")
            return False

    def _extract_slug(self, content: str, fallback_id: str) -> str:
        """Extracts slug from frontmatter or generates fallback."""
        slug = f"article-{fallback_id}"
        if "slug:" in content:
            match = re.search(r'slug:\s*"?([^"\n]+)"?', content)
            if match:
                slug = match.group(1).strip()
        return slug
