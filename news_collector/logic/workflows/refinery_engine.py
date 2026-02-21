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

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from news_collector.components.editorial.ai_editor import EditorAgent
from news_collector.components.editorial.auditor import EditorialAuditor
from news_collector.components.publishing import GitHubPublisher

if "TYPE_CHECKING":
    from news_collector.storage.database import DatabaseManager

logger = logging.getLogger("RefineryEngine")

# Removing duplicate import if it exists further down

MANIFEST_FILENAME = "refinery_manifest.json"


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
        self.config = config
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
        self.enforcement_log_path = (
            Path(data_dir) / "editorial_policy_enforcement_log.jsonl"
        )

        self.editor = editor_agent

        # Original: self.editor = editor_agent
        # Let's stick to original args where possible to avoid breaking other things
        # But my previous edit replaced self.editor = editor_agent with self.editor = EditorAgent(self.config)
        # If I want to be safe, I should use the passed args if they are valid.
        # However, looking at imports, EditorAgent is imported.
        # Let's assume the passed `editor_agent` is what we want.
        self.editor = editor_agent
        self.git = git_handler

        # Auditor & Executor
        self.auditor = EditorialAuditor(self.config)

        # ThreadPool for Auditor (Non-blocking)
        from concurrent.futures import ThreadPoolExecutor

        self.executor = ThreadPoolExecutor(max_workers=1)
        self._last_audit_future = None

        self._manifest_cache: Dict[str, str] = {}
        self._manifest_loaded = False

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
        posts_dir = target_dir / "src/content/posts"

        # Priority 1: Check DB for immutable identity
        db_canonical_slug = (
            self.db.get_canonical_slug(article_id)
            if hasattr(self.db, "get_canonical_slug")
            else None
        )

        canonical_date = None
        output_filename = None

        if db_canonical_slug:
            logger.info(
                f"🔒 Identity: Locked to DB canonical slug: {db_canonical_slug}"
            )
            # The slug in DB includes the date prefix e.g. "2024-01-25-my-article"
            output_filename = f"{db_canonical_slug}.md"

            # Extract date from valid slug
            match = re.match(r"^(\d{4}-\d{2}-\d{2})-", db_canonical_slug)
            if match:
                canonical_date = match.group(1)
            else:
                # Should not happen if data integrity is kept, but safe fallback
                canonical_date = datetime.now().strftime("%Y-%m-%d")

        else:
            # Priority 2: Check File System (Legacy Recovery)
            existing_file = self._find_existing_file(posts_dir, article_id)
            if existing_file:
                logger.info(f"♻️ Idempotency: Found existing file {existing_file.name}")
                output_filename = existing_file.name
                # Extract date
                match = re.match(r"^(\d{4}-\d{2}-\d{2})-", output_filename)
                if match:
                    canonical_date = match.group(1)

                # SELF-HEALING: Backfill DB
                slug_stem = output_filename.replace(".md", "")
                if hasattr(self.db, "set_canonical_slug"):
                    self.db.set_canonical_slug(article_id, slug_stem)
                    logger.info(f"💾 Backfilled canonical slug to DB: {slug_stem}")

            else:
                # Priority 3: Creation Mode (Strict Determinism)
                # MUST use source date, not system time, if available.
                src_date = article.get("published_date")

                if src_date:
                    if isinstance(src_date, datetime):
                        canonical_date = src_date.strftime("%Y-%m-%d")
                    else:
                        s_date = str(src_date).strip()
                        # Try ISO format
                        match = re.match(r"^\d{4}-\d{2}-\d{2}", s_date)
                        if match:
                            canonical_date = match.group(0)

                # If still no date, use collected_date or NOW as absolute last resort
                if not canonical_date:
                    collected = article.get("collected_date")
                    if collected and isinstance(collected, datetime):
                        canonical_date = collected.strftime("%Y-%m-%d")
                    else:
                        canonical_date = datetime.now().strftime("%Y-%m-%d")

        # 2. AI Processing
        # We pass canonical_date to ensure the frontmatter matches our filename expectation
        logger.info(f"Processing with intended date: {canonical_date}")

        # --- IMAGE HANDLING ---
        # 2a. Download Remote Image (if present)
        # We need a slug for the image filename.
        # If we have a DB slug, use that. If not, construct a tentative one.
        # Note: If we don't have a DB slug yet, the filename might change slightly later
        # (e.g. if we add a random suffix for uniqueness), but using a base slug here is fine.

        image_slug = db_canonical_slug  # e.g. "2024-01-01-my-title"
        if not image_slug:
            # Create a safe base slug from ID or Title
            # Using same logic as below (but simplified for image filename)
            safe_id = re.sub(r"[^a-zA-Z0-9_-]", "", article_id)
            image_slug = f"{canonical_date}-{safe_id}"

        raw_image_url = article.get("image_url")
        if raw_image_url and raw_image_url.startswith("http"):
            local_image_ref = self._download_image(
                raw_image_url, image_slug, target_dir
            )
            if local_image_ref:
                logger.info(f"Updated article image to local asset: {local_image_ref}")
                article["image_url"] = local_image_ref
            else:
                logger.warning(
                    f"Failed to download image from {raw_image_url} (or download failed). Enforcing local policy with default."
                )
                article["image_url"] = "~/assets/images/default.png"

        # Apply Policy to Editor
        self.editor.critic_threshold = self.policy.critic_threshold
        logger.info(
            f"Enforcing Critic Threshold: {self.policy.critic_threshold} (Mode: {self.policy.mode})"
        )

        try:
            refined_content = self.editor.process_article(
                article, override_date=canonical_date
            )
        except ValueError as ve:
            if "Translation Guardrail" in str(ve):
                logger.warning(f"⛔ Blocked by Editorial Policy (Critic): {ve}")
                return False
            raise ve

        # --- AUDIT PHASE (True Non-Blocking & Backpressure) ---
        # We audit the refined content to score it.
        try:
            # BACKPRESSURE GUARD (Objective 4):
            # If a previous audit is still running/queued, skip this one to prevent unbounded growth.
            # invalid/done futures are safe to overwrite.
            if self._last_audit_future and not self._last_audit_future.done():
                logger.warning(
                    f"Auditor Backpressure: Skipping audit for {article_id} (Previous task still active)"
                )
            elif self.auditor.should_run_fast(article, refined_content):
                logger.info(
                    f"Submitting Auditor task for {article_id} (Non-blocking)..."
                )
                self._last_audit_future = self.executor.submit(
                    self.auditor.audit_article_sync,
                    article_id=article_id,
                    content=refined_content,
                    source_url=article.get("url") or article.get("source_url") or "",
                    article_data=article,
                )
        except Exception as e:
            logger.error(f"Auditor submission failed for {article_id}: {e}")

        # 3. Determine Output Filename (if not yet locked)
        if not output_filename:
            slug_part = self._extract_slug(refined_content, article_id)
            # FORCE VALIDATION: Ensure slug doesn't accidentally contain a date prefix again
            # if the AI decided to include it.

            # Construct the immutable slug
            final_slug = f"{canonical_date}-{slug_part}"
            output_filename = f"{final_slug}.md"

            # CRITICAL: Persist immediately
            if hasattr(self.db, "set_canonical_slug"):
                try:
                    self.db.set_canonical_slug(article_id, final_slug)
                    logger.info(f"🔒 Identity Created: {final_slug}")
                except Exception as e:
                    logger.error(f"Failed to persist canonical slug: {e}")
                    pass

        # --- POLICY ENFORCEMENT: AUDITOR CHECK ---
        # OBJECTIVE: Enforce Policy BEFORE Persistence (Writing File / Manifest / Git)
        # Check cached score first.
        cached_score = self.auditor.get_cached_score(article_id)

        if not self._enforce_editorial_policy(article_id, cached_score):
            logger.warning(
                f"⛔ Article {article_id} rejected by Editorial Policy (Auditor/Strictness)."
            )
            return False

        # 4. Save File
        posts_dir.mkdir(parents=True, exist_ok=True)
        target_file_path = posts_dir / output_filename

        target_file_path.write_text(refined_content, encoding="utf-8")
        logger.info(f"Written content to {target_file_path}")

        # Update Sidecar Manifest
        self._update_manifest(posts_dir, article_id, output_filename)

        # (Auditor checking validation block removed from here as it is done above)

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
        """
        Scans for existing file using O(1) manifest lookup, falling back to scanner.
        """
        if not posts_dir.exists():
            return None

        # 1. Try Manifest Lookup (Fast Path)
        self._load_manifest(posts_dir)
        if article_id in self._manifest_cache:
            filename = self._manifest_cache[article_id]
            file_path = posts_dir / filename
            if file_path.exists():
                logger.info(f"⚡ Manifest hit: {article_id} -> {filename}")
                return file_path
            else:
                logger.warning(f"Manifest stale: {filename} not found on disk.")
                # Fallthrough to robust scan

        # 2. Legacy Linear Scan (Slow Path)
        logger.info(f"🐢 Slow scan triggered for {article_id}")
        try:
            for file_path in posts_dir.glob("*.md"):
                try:
                    # Quick check: read first 50 lines (Frontmatter)
                    content_head = []
                    with open(file_path, "r") as f:
                        for _ in range(50):
                            line = f.readline()
                            if not line:
                                break
                            content_head.append(line)

                    full_head = "".join(content_head)
                    if f'refinery_id: "{article_id}"' in full_head:
                        # Self-heal manifest
                        self._update_manifest(posts_dir, article_id, file_path.name)
                        return file_path
                except Exception:  # noqa: S112
                    continue
        except Exception as e:
            logger.error(f"Error scanning for existing files: {e}")

        return None

    def _load_manifest(self, posts_dir: Path):
        """Loads the sidecar manifest into memory if not already loaded."""
        if self._manifest_loaded:
            return

        manifest_path = posts_dir / MANIFEST_FILENAME
        if manifest_path.exists():
            try:
                data = json.loads(manifest_path.read_text(encoding="utf-8"))
                self._manifest_cache = data
                self._manifest_loaded = True
                logger.info(f"Loaded refinery manifest with {len(data)} entries")
            except Exception as e:
                logger.error(f"Failed to load manifest: {e}")
                self._manifest_cache = {}
        else:
            self._manifest_cache = {}
            self._manifest_loaded = True  # Loaded empty

    def _update_manifest(self, posts_dir: Path, article_id: str, filename: str):
        """Updates the in-memory cache and persists the manifest to disk."""
        self._load_manifest(posts_dir)  # Ensure loaded

        if self._manifest_cache.get(article_id) == filename:
            return  # No change

        self._manifest_cache[article_id] = filename

        # Persist
        try:
            manifest_path = posts_dir / MANIFEST_FILENAME
            manifest_path.write_text(
                json.dumps(self._manifest_cache, indent=2, sort_keys=True),
                encoding="utf-8",
            )
        except Exception as e:
            logger.error(f"Failed to persist manifest: {e}")

    def _extract_slug(self, content: str, fallback_id: str) -> str:
        """Extracts slug from frontmatter or generates fallback."""
        slug = f"article-{fallback_id}"
        if "slug:" in content:
            match = re.search(r'slug:\s*"?([^"\n]+)"?', content)
            if match:
                slug = match.group(1).strip()
        return slug

    def _download_image(self, url: str, slug: str, target_dir: Path) -> str | None:
        """
        Downloads a remote image to the local assets directory.
        Returns the Astro-compatible local path (e.g. "~/assets/images/slug.jpg")
        or None if download fails.
        """
        if not url or not url.startswith("http"):
            return None

        # Determine extension
        # Simple heuristic from URL, default to .jpg if unknown/complex
        ext = ".jpg"
        if ".png" in url.lower():
            ext = ".png"
        elif ".webp" in url.lower():
            ext = ".webp"
        elif ".jpeg" in url.lower():
            ext = ".jpg"

        filename = f"{slug}{ext}"

        # Paths
        assets_dir = target_dir / "src/assets/images"
        assets_dir.mkdir(parents=True, exist_ok=True)
        local_path = assets_dir / filename

        logger.info(f"Downloading image from {url} to {local_path}")

        from news_collector.infrastructure.requests_client import RobustRequestsClient

        try:
            with RobustRequestsClient() as client:
                response = client.get(url, timeout=15)
                local_path.write_bytes(response.content)
                logger.info(f"Image saved: {local_path}")
                # Return Astro format
                return f"~/assets/images/{filename}"
        except Exception as e:
            logger.error(f"Failed to download image {url}: {e}")
            return None

    def _enforce_editorial_policy(
        self, article_id: str, cached_score: dict | None
    ) -> bool:
        """
        Enforces editorial policy deterministically and logs result.
        Returns True if allowed, False if blocked.
        """
        decision = "allowed"
        reason = "Non-blocking check passed (Fail-Open) or Score Sufficient"
        score_data = {}

        try:
            # Fail-Open if no score available (Non-Blocking Auditor)
            # Using strict usage of 'is None'
            if cached_score is None:
                decision = "allowed"
                reason = "No Auditor score available (Non-blocking default)"
                return True

            score_data = cached_score
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
