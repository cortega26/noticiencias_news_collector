import argparse
import json
import shutil
import sys
from pathlib import Path

import git

# Add project root to sys.path to allow imports if running standalone or via streamlit
project_root = Path(__file__).resolve().parents[2]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from noticiencias.config_manager import load_config

from apps.refinery.published_content import (
    append_deleted_route_smoke_check,
    find_published_article_by_file_name,
    find_published_article_by_refinery_id,
    infer_published_article_route,
    prune_hero_placeholder_allowlist_for_post,
    prune_refinery_manifest_for_post,
)
from news_collector.components.publishing import GitHubPublisher
from news_collector.logic.workflows.publication_pipeline import (
    PROCESSED_LOG_FILE,
    SOURCE_DIR,
    TARGET_DIR,
    TEMP_DIR,
    _export_identity_matches_db,
    _is_file_lock_error,
    _load_export_articles,
    _safe_clone_source_repo,
    _select_export_articles,
    _unique_post_slug,
    run_collector_script,
    run_publication_pipeline,
)
from news_collector.utils.logger import get_logger

logger = get_logger().create_module_logger("Orchestrator")

# Re-exported for backwards compatibility: the publish-dispatch glue moved
# verbatim to news_collector.logic.workflows.publication_pipeline (plan 106).
# External importers (tests, tooling) keep resolving these names here.
__all__ = [
    "PROCESSED_LOG_FILE",
    "SOURCE_DIR",
    "TARGET_DIR",
    "TEMP_DIR",
    "_export_identity_matches_db",
    "_is_file_lock_error",
    "_load_export_articles",
    "_safe_clone_source_repo",
    "_select_export_articles",
    "_unique_post_slug",
    "delete_article",
    "main",
    "run_collector_script",
]


def main(
    fetch_only=False,
    process_id=None,
    article_url=None,
    dev=False,
    skip_visuals=False,
    export_path=None,
    fast_mode=False,
    process_new_content=False,
    dry_run=False,
):
    """Legacy UI entrypoint — thin delegate over the workflow-layer pipeline.

    Forwards every mode unchanged to
    `news_collector.logic.workflows.publication_pipeline.run_publication_pipeline`.
    This wrapper exists so the Streamlit panel (`admin_panel.py`, which loads
    this file directly) and existing callers keep working with identical
    behavior; the pipeline module owns the stage inventory.
    """
    return run_publication_pipeline(
        fetch_only=fetch_only,
        process_id=process_id,
        article_url=article_url,
        dev=dev,
        skip_visuals=skip_visuals,
        export_path=export_path,
        fast_mode=fast_mode,
        process_new_content=process_new_content,
        dry_run=dry_run,
    )


def _normalize_delete_target(target: str | dict[str, str]) -> dict[str, str]:
    if isinstance(target, str):
        value = target.strip()
        if not value:
            raise ValueError("Delete target is empty.")
        return {"refinery_id": value}

    if not isinstance(target, dict):
        raise ValueError("Delete target must be a string or a dict.")

    normalized: dict[str, str] = {}
    for key in ("refinery_id", "file_name"):
        raw_value = target.get(key)
        if raw_value is None:
            continue
        value = str(raw_value).strip()
        if value:
            normalized[key] = value

    if normalized.get("file_name"):
        normalized["file_name"] = Path(normalized["file_name"]).name

    if not normalized:
        raise ValueError("Delete target requires 'refinery_id' or 'file_name'.")

    return normalized


def delete_article(target: str | dict[str, str]) -> dict:  # noqa: C901
    """
    Locates and deletes an article from the target repo using an exact published
    identifier (`refinery_id` or `file_name`) and creates a Pull Request.
    """
    target_info = _normalize_delete_target(target)
    logger.info("Initiating One-Click Unpublish for target: {}", target_info)

    try:
        config = load_config()
        git_handler = GitHubPublisher(config.github.token or "")

        # 1. Clone Target
        if TARGET_DIR.exists():
            shutil.rmtree(TARGET_DIR, ignore_errors=True)
        git_handler.clone_repo(config.github.target_repo_url, TARGET_DIR)
        target_repo_obj = git.Repo(TARGET_DIR)

        # 2. Search for File
        posts_dir = TARGET_DIR / "src/content/posts"
        target_file = None
        target_article = None

        if posts_dir.exists():
            refinery_id = target_info.get("refinery_id")
            if refinery_id:
                target_article = find_published_article_by_refinery_id(
                    posts_dir, refinery_id
                )
            if target_article is None and target_info.get("file_name"):
                target_article = find_published_article_by_file_name(
                    posts_dir, target_info["file_name"]
                )
            if target_article is not None:
                target_file = target_article.file_path

        if not target_file or target_article is None:
            logger.warning(
                "Delete target {} not found in published content.", target_info
            )
            return {
                "status": "error",
                "message": "Article not found in remote content for the requested identifier.",
            }

        # 3. Create Branch
        branch_name = git_handler.create_branch(
            target_repo_obj, branch_prefix="delete/article"
        )

        # 4. Delete File
        filename = target_file.name
        route_path = infer_published_article_route(target_article)
        removed_manifest_keys = prune_refinery_manifest_for_post(
            TARGET_DIR,
            file_name=filename,
            refinery_id=target_article.refinery_id,
        )
        target_file.unlink()
        logger.info(f"Deleted file: {filename}")
        removed_allowlist_entry = prune_hero_placeholder_allowlist_for_post(
            TARGET_DIR, target_file
        )
        if removed_allowlist_entry:
            logger.info(
                f"Removed stale hero placeholder allowlist entry for {filename}"
            )
        if removed_manifest_keys:
            logger.info(
                "Removed stale refinery manifest entries for {}: {}",
                filename,
                ", ".join(removed_manifest_keys),
            )
        if route_path:
            append_deleted_route_smoke_check(
                TARGET_DIR,
                route_path=route_path,
                file_name=filename,
                reason="Route should disappear after merged unpublish.",
            )

        # 5. Commit & Push
        git_handler.commit_and_push(
            target_repo_obj, f"Unpublish article: {filename}", branch_name
        )

        # 6. Create PR
        pr_url = git_handler.create_pull_request(
            repo_url=config.github.target_repo_url,
            branch_name=branch_name,
            title=f"Unpublish: {filename}",
            body="\n".join(
                [
                    f"Request to unpublish/delete {filename}.",
                    "",
                    (
                        f"Refinery ID: {target_article.refinery_id}"
                        if target_article.refinery_id
                        else "Refinery ID: n/a (filename-backed delete)"
                    ),
                    f"File Name: {filename}",
                    *([f"Route Smoke Check: {route_path}"] if route_path else []),
                ]
            ),
        )

        return {
            "status": "success",
            "pr_url": pr_url,
            "file_name": filename,
            "route_path": route_path,
            "manifest_entries_removed": removed_manifest_keys,
            "allowlist_entry_removed": removed_allowlist_entry,
        }

    except Exception as e:
        logger.error(f"Failed to delete article: {e}")
        return {"status": "error", "message": str(e)}


if __name__ == "__main__":
    import shutil  # Need to ensure imports are present if we use them

    import git

    parser = argparse.ArgumentParser(description="Noticiencias Refinery Orchestrator")
    parser.add_argument(
        "--fetch-only",
        action="store_true",
        help="Only clone/pull source repo, do not process articles.",
    )
    parser.add_argument(
        "--process-id", type=str, help="Process a specific article ID (or title) only."
    )
    parser.add_argument(
        "--article-url",
        type=str,
        help="Fetch and process a specific article URL through the manual ingestion path.",
    )
    parser.add_argument(
        "--dev",
        action="store_true",
        help="Enable development features (like mock generation).",
    )
    parser.add_argument(
        "--skip-visuals",
        action="store_true",
        help="Skip the visual analysis step (faster).",
    )
    parser.add_argument(
        "--delete-id", type=str, help="Unpublish/Delete a specific article ID."
    )
    parser.add_argument(
        "--export-path", type=str, help="Use specific JSON export file."
    )
    args = parser.parse_args()

    if args.delete_id:
        result = delete_article(args.delete_id)
        print(json.dumps(result))  # Output for caller
        sys.exit(0 if result["status"] == "success" else 1)

    main(
        fetch_only=args.fetch_only,
        process_id=args.process_id,
        article_url=args.article_url,
        dev=args.dev,
        skip_visuals=args.skip_visuals,
        export_path=args.export_path,
    )
