"""
Module role: Manages file I/O for the target post repository — writing article
files, maintaining the sidecar manifest, and resolving existing file identities.

Owns:
- write_article: atomic file write with path-traversal guard + manifest update + prune
- load_manifest / update_manifest: manifest load/persist lifecycle (atomic JSON write)
- find_existing_file: O(1) manifest lookup with O(n) slow-scan fallback + self-heal

Does NOT own:
- Canonical identity resolution (see publication_identity.py)
- Git operations
- Image download
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict

from apps.refinery.published_content import prune_hero_placeholder_allowlist_for_post
from news_collector.contracts import MANIFEST_FILENAME
from news_collector.utils.logger import get_logger

logger = get_logger().create_module_logger("TargetRepoWriter")


class TargetRepoWriter:
    """
    Handles all file-system I/O for the target post repository.

    Instantiate once per RefineryEngine.  The manifest is lazily loaded and
    cached in memory across multiple calls within the same process lifetime.
    """

    def __init__(self) -> None:
        self._manifest_cache: Dict[str, str] = {}
        self._manifest_loaded: bool = False

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def write_article(
        self,
        *,
        posts_dir: Path,
        output_filename: str,
        content: str,
        article_id: str,
        target_dir: Path,
    ) -> Path:
        """
        Write refined article content to *posts_dir/output_filename*.

        Raises:
            ValueError: if *output_filename* would resolve outside *posts_dir*
                        (path-traversal guard).
            OSError: on underlying file-system errors.

        Returns the Path to the written file.
        """
        posts_dir.mkdir(parents=True, exist_ok=True)
        target_file_path = posts_dir / output_filename

        resolved_target = target_file_path.resolve()
        resolved_posts = posts_dir.resolve()

        # NC-BE-015 S0 GUARD: Path Traversal Check
        try:
            resolved_target.relative_to(resolved_posts)
        except ValueError as err:
            raise ValueError(
                f"Path traversal detected: {resolved_target} is outside {resolved_posts}"
            ) from err

        target_file_path.write_text(content, encoding="utf-8")
        logger.info("Written content to {}", target_file_path)

        if prune_hero_placeholder_allowlist_for_post(target_dir, target_file_path):
            logger.info(
                "Removed stale hero placeholder allowlist entry for {}", output_filename
            )

        self.update_manifest(posts_dir, article_id, output_filename)
        return target_file_path

    def load_manifest(self, posts_dir: Path) -> None:
        """Load the sidecar manifest into memory if not already loaded."""
        if self._manifest_loaded:
            return

        manifest_path = posts_dir / MANIFEST_FILENAME
        if manifest_path.exists():
            try:
                data = json.loads(manifest_path.read_text(encoding="utf-8"))
                self._manifest_cache = data
                self._manifest_loaded = True
                logger.info("Loaded refinery manifest with {} entries", len(data))
            except Exception as e:
                logger.error("Failed to load manifest: {}", e)
                self._manifest_cache = {}
        else:
            self._manifest_cache = {}
        self._manifest_loaded = True

    def update_manifest(self, posts_dir: Path, article_id: str, filename: str) -> None:
        """
        Update the in-memory cache and atomically persist the manifest to disk.

        Uses tmp + os.replace() so the manifest is always complete JSON even on
        process interruption (B-05 / F-0025).
        """
        self.load_manifest(posts_dir)  # ensure loaded

        if self._manifest_cache.get(article_id) == filename:
            return  # no change

        self._manifest_cache[article_id] = filename

        try:
            manifest_path = posts_dir / MANIFEST_FILENAME
            tmp_path = manifest_path.with_suffix(".tmp")
            tmp_path.write_text(
                f"{json.dumps(self._manifest_cache, indent=2, sort_keys=True)}\n",
                encoding="utf-8",
            )
            os.replace(str(tmp_path), str(manifest_path))
        except Exception as e:
            logger.error("Failed to persist manifest: {}", e)

    def find_existing_file(self, posts_dir: Path, article_id: str) -> Path | None:
        """
        Scan for an existing file for *article_id*.

        Strategy:
        1. Manifest fast path (O(1)).
        2. Linear scan fallback (O(n)) — reads first 50 lines of each .md file.
           Self-heals the manifest when a match is found via slow scan.

        Returns the Path if found, None otherwise.
        """
        if not posts_dir.exists():
            return None

        # 1. Manifest fast path
        self.load_manifest(posts_dir)
        if article_id in self._manifest_cache:
            filename = self._manifest_cache[article_id]
            file_path = posts_dir / filename
            if file_path.exists():
                logger.info("⚡ Manifest hit: {} -> {}", article_id, filename)
                return file_path
            else:
                logger.warning("Manifest stale: {} not found on disk.", filename)
                # fall through to slow scan

        # 2. Linear scan (slow path)
        logger.info("🐢 Slow scan triggered for {}", article_id)
        try:
            for file_path in posts_dir.glob("*.md"):
                try:
                    content_head: list[str] = []
                    with open(file_path, "r") as f:
                        for _ in range(50):
                            line = f.readline()
                            if not line:
                                break
                            content_head.append(line)

                    if f'refinery_id: "{article_id}"' in "".join(content_head):
                        # Self-heal the manifest
                        self.update_manifest(posts_dir, article_id, file_path.name)
                        return file_path
                except (OSError, UnicodeDecodeError):
                    continue
        except Exception as e:
            logger.error("Error scanning for existing files: {}", e)

        return None
