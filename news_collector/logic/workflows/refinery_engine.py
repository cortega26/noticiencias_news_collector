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
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from news_collector.components.editorial.ai_editor import EditorAgent
from news_collector.components.editorial.auditor import EditorialAuditor
from news_collector.components.publishing import GitHubPublisher
from news_collector.utils.logger import get_logger

if "TYPE_CHECKING":
    from news_collector.storage.database import DatabaseManager

logger = get_logger().create_module_logger("RefineryEngine")

# Removing duplicate import if it exists further down

MANIFEST_FILENAME = "refinery_manifest.json"
QUOTED_DATE_ONLY_FRONTMATTER_RE = re.compile(
    r'(?m)^[A-Za-z_][A-Za-z0-9_-]*:\s*(["\'])\d{4}-\d{2}-\d{2}\1\s*$'
)


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
        runtime_dir = Path(data_dir) / "runtime"
        runtime_dir.mkdir(parents=True, exist_ok=True)
        self.enforcement_log_path = (
            runtime_dir / "editorial_policy_enforcement_log.jsonl"
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
        self._last_audit_future: Optional[concurrent.futures.Future[Dict[str, Any]]] = None

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
                return False

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
                    if hasattr(src_date, "strftime"):
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
                    if collected and hasattr(collected, "strftime"):
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
        if isinstance(raw_image_url, str):
            raw_image_url = raw_image_url.strip()
        
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
                article, override_date=canonical_date, explicit_article_id=article_id
            )
        except ValueError as ve:
            if "Translation Guardrail" in str(ve):
                logger.warning(f"⛔ Blocked by Editorial Policy (Critic): {ve}")
                return False
            raise ve

        audit_should_run = False
        try:
            audit_should_run = self.auditor.should_run_fast(article, refined_content)
        except Exception as e:
            logger.warning(f"Auditor pre-check failed for {article_id}: {e}")

        # 3. Determine Output Filename (if not yet locked)
        if not output_filename:
            slug_part = self._extract_slug(refined_content, article_id)
            # FORCE VALIDATION: Ensure slug doesn't accidentally contain a date prefix again
            # if the AI decided to include it.

            # Construct the immutable slug
            final_slug = f"{canonical_date}-{slug_part}"
            output_filename = f"{final_slug}.md"

            # --- NC-BE-015: Collision Check ---
            # If target exists but priority 2 (_find_existing_file) didn't catch it,
            # it belongs to a different article. Append deterministic counter to prevent overwrite.
            target_file_path = posts_dir / output_filename
            iteration = 1
            while target_file_path.exists():
                final_slug = f"{canonical_date}-{slug_part}-{iteration}"
                output_filename = f"{final_slug}.md"
                target_file_path = posts_dir / output_filename
                iteration += 1

        # --- POLICY ENFORCEMENT: AUDITOR CHECK ---
        # OBJECTIVE: Enforce Policy BEFORE Persistence (Writing File / Manifest / Git)
        # Check cached score first.
        cached_score = self.auditor.get_cached_score(article_id)

        if not self._enforce_editorial_policy(article_id, cached_score):
            logger.warning(
                f"⛔ Article {article_id} rejected by Editorial Policy (Auditor/Strictness)."
            )
            return False

        if self._has_quoted_date_only_frontmatter(refined_content):
            logger.error(
                "Quoted date-only frontmatter detected for article %s. "
                "Aborting before branch/commit/push.",
                article_id,
            )
            return False

        # Persist canonical slug AFTER policy approval (B-02 / F-0018)
        if hasattr(self.db, "set_canonical_slug"):
            try:
                persisted = self.db.set_canonical_slug(article_id, final_slug)
                if persisted:
                    logger.info(f"🔒 Identity Created: {final_slug}")
                else:
                    logger.info(
                        f"🔒 Canonical slug already exists for article {article_id}: {final_slug}"
                    )
            except Exception as e:
                logger.error(f"Failed to persist canonical slug: {e}")

        # 4. Create Branch
        # Create/sync the branch before writing files so branch collisions or
        # remote sync failures do not leave uncommitted content edits behind.
        branch_slug = output_filename.replace(".md", "")
        branch_name = self.git.create_branch(
            target_repo_obj, branch_prefix="content/update", explicit_name=branch_slug
        )

        # 5. Save File
        posts_dir.mkdir(parents=True, exist_ok=True)
        target_file_path = posts_dir / output_filename

        resolved_target = target_file_path.resolve()
        resolved_posts = posts_dir.resolve()

        # --- NC-BE-015 S0 GUARD: Path Traversal Check ---
        try:
            resolved_target.relative_to(resolved_posts)
        except ValueError:
            logger.error(
                f"🚨 S0 GUARD: Path traversal detected. {resolved_target} is outside {resolved_posts}"
            )
            return False

        target_file_path.write_text(refined_content, encoding="utf-8")
        logger.info(f"Written content to {target_file_path}")

        # Update Sidecar Manifest
        self._update_manifest(posts_dir, article_id, output_filename)

        # (Auditor checking validation block removed from here as it is done above)

        # 6. Commit & Push
        self.git.commit_and_push(
            target_repo_obj, f"Update article: {output_filename}", branch_name
        )

        # 7. Create PR
        # Resolve target repo URL with backward-compatible lookup
        repo_url = None
        github_cfg = getattr(self.config, "github", None)
        if github_cfg:
            # github may be an object or a dict depending on how config is passed in
            repo_url = getattr(github_cfg, "target_repo_url", None) or (
                github_cfg.get("target_repo_url")
                if isinstance(github_cfg, dict)
                else None
            )
        if repo_url is None:
            # Legacy flat attribute support (older code paths/tests)
            repo_url = getattr(self.config, "target_repo_url", None)
            if repo_url is None and isinstance(self.config, dict):
                repo_url = self.config.get("target_repo_url")

        if not repo_url:
            raise AttributeError(
                "Invalid configuration: missing github.target_repo_url"
            )

        source_id = str(article.get("source_id", "")).strip() or "unknown"
        source_name = str(article.get("source_name", "")).strip() or "unknown"
        pr_body = (
            f"Automated submission for {article_id}.\n\n"
            f"Source ID: {source_id}\n"
            f"Source Name: {source_name}\n\n"
            "Processed by Noticiencias Refinery."
        )

        pr_url = self.git.create_pull_request(
            repo_url=repo_url,
            branch_name=branch_name,
            title=f"News: {output_filename.replace('.md', '')}",
            body=pr_body,
        )

        if pr_url:
            logger.info(f"Pull Request created successfully: {pr_url}")
            # Mark processed in Main DB
            numeric_id = None
            try:
                numeric_id = int(article_id)
                self.db.mark_article_published(numeric_id, pr_url)
            except ValueError:
                logger.warning(
                    f"Could not mark non-numeric ID {article_id} in main DB. Skipping state update."
                )

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

            return True
        else:
            logger.error("Failed to create PR.")
            return False

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
                        "Optional auditor did not pass for article %s: %s",
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
                except (OSError, UnicodeDecodeError):
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
        import unicodedata

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
        slug = (
            unicodedata.normalize("NFKD", slug)
            .encode("ASCII", "ignore")
            .decode("utf-8")
        )
        slug = re.sub(r"[^a-zA-Z0-9\-_]", "-", slug)
        slug = re.sub(r"-+", "-", slug).strip("-").lower()

        if not slug or slug == "-":
            slug = f"article-{fallback_id}"

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
