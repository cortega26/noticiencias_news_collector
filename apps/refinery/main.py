import argparse
import json
import re
import shutil
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import git

# Add project root to sys.path to allow imports if running standalone or via streamlit
project_root = Path(__file__).resolve().parents[2]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import asyncio

from news_collector.components.editorial import EditorAgent
from news_collector.components.publishing import GitHubPublisher
from news_collector.contracts.adapters import adapt_export_article_to_collector_payload
from news_collector.infrastructure.llm.model_registry import resolve_ollama_stage_models
from news_collector.logic.workflows.refinery_engine import RefineryEngine

# from news_collector.components.editorial import EditorAgent # Removed duplicate
from news_collector.storage.database import DatabaseManager
from news_collector.system import create_system
from news_collector.utils.logger import get_logger
from noticiencias.config_manager import load_config

logger = get_logger().create_module_logger("Orchestrator")

PROCESSED_LOG_FILE = "processed_log.json"
TEMP_DIR = Path("temp")
SOURCE_DIR = TEMP_DIR / "source"
TARGET_DIR = TEMP_DIR / "target"
# DB_PATH = Path("refinery.db") # Deprecated


def _is_file_lock_error(exc: Exception) -> bool:
    winerror = getattr(exc, "winerror", None)
    if winerror == 32:
        return True
    message = str(exc).lower()
    return (
        "being used by another process" in message
        or "utilizado por otro proceso" in message
    )


def _unique_post_slug(
    *,
    posts_dir: Path,
    date_str: str,
    base_slug: str,
    article_id: str,
) -> tuple[str, Path]:
    candidate_slug = base_slug
    output_path = posts_dir / f"{date_str}-{candidate_slug}.md"
    if not output_path.exists():
        return candidate_slug, output_path

    safe_suffix = re.sub(r"[^a-z0-9]+", "", article_id.lower())[:6]
    if not safe_suffix:
        safe_suffix = uuid.uuid4().hex[:6]

    candidate_slug = f"{base_slug}-{safe_suffix}"
    output_path = posts_dir / f"{date_str}-{candidate_slug}.md"
    if not output_path.exists():
        return candidate_slug, output_path

    for attempt in range(2, 100):
        candidate_slug = f"{base_slug}-{safe_suffix}-{attempt}"
        output_path = posts_dir / f"{date_str}-{candidate_slug}.md"
        if not output_path.exists():
            return candidate_slug, output_path

    raise RuntimeError(
        f"Unable to generate unique slug for article {article_id} in {posts_dir}"
    )


def _safe_clone_source_repo(
    git_handler: GitHubPublisher,
    repo_url: str,
    source_dir: Path,
) -> Path:
    try:
        git_handler.clone_repo(repo_url, source_dir)
        return source_dir
    except Exception as exc:
        if _is_file_lock_error(exc) and (source_dir / ".git").exists():
            logger.warning(
                "Source repo locked during cleanup; using existing clone at "
                f"{source_dir}. Error: {exc}"
            )
            return source_dir
        raise


def _load_export_articles(  # noqa: C901
    export_path: Path,
    db_manager: DatabaseManager,
    process_id: Optional[str],
) -> List[Dict[str, Any]]:
    try:
        with open(export_path, "r", encoding="utf-8") as f:
            export_payload = json.load(f)
    except Exception as exc:
        logger.error(f"Failed to load collector export at {export_path}: {exc}")
        return []

    schema_version_raw: Any = None
    contract_name = ""

    header_articles = export_payload
    if isinstance(export_payload, dict):
        schema_version_raw = export_payload.get("schema_version")
        contract_name = str(export_payload.get("contract", "")).strip()
        header_articles = export_payload.get("articles", [])
    elif isinstance(export_payload, list):
        # Legacy exports may be a raw list without a header object.
        schema_version_raw = 1

    if not isinstance(header_articles, list):
        logger.error(
            f"Export payload has unexpected format at {export_path}: {type(header_articles)}"
        )
        return []

    try:
        schema_version = (
            int(schema_version_raw) if schema_version_raw is not None else None
        )
    except (TypeError, ValueError):
        logger.warning(
            "Export payload schema_version is invalid (%r). Treating payload as legacy v1.",
            schema_version_raw,
        )
        schema_version = 1

    is_legacy_export = schema_version == 1 or contract_name.endswith(".v1")
    if schema_version is None:
        logger.warning(
            "Export payload at %s has no schema_version. Assuming legacy v1 compatibility path.",
            export_path,
        )
        is_legacy_export = True
    elif is_legacy_export:
        logger.warning(
            "Legacy export schema detected at %s (schema_version=%s, contract=%s). "
            "Applying source_name->source_id compatibility mapping.",
            export_path,
            schema_version,
            contract_name or "n/a",
        )

    source_name_fallback_enabled = True  # Always enable fallback to prevent syncing sync crashes from corrupted payloads

    # Deterministic source identity resolver (source_name -> source_id).
    # Duplicate display names are excluded to avoid ambiguous mappings.
    from news_collector.config.sources import ALL_SOURCES

    source_name_to_id: Dict[str, str] = {}
    ambiguous_names: set[str] = set()
    for source_id, source_cfg in ALL_SOURCES.items():
        name = str(source_cfg.get("name", "")).strip()
        if not name:
            continue
        key = name.casefold()
        existing = source_name_to_id.get(key)
        if existing and existing != source_id:
            ambiguous_names.add(key)
            source_name_to_id.pop(key, None)
            continue
        source_name_to_id[key] = source_id

    if ambiguous_names:
        logger.warning(
            "Detected ambiguous source display names in config; "
            "fallback source_name->source_id mapping disabled for %d names.",
            len(ambiguous_names),
        )

    articles = []
    for art in header_articles:
        art_id = str(art.get("id", art.get("title")))
        if process_id and str(art_id) != str(process_id):
            continue

        try:
            art = adapt_export_article_to_collector_payload(
                art,
                source_name_to_id=(
                    source_name_to_id if source_name_fallback_enabled else None
                ),
            )
        except ValueError as exc:
            logger.error(
                "Invalid export payload for article %s: %s | keys=%s | source_id=%r | "
                "source=%r | sourceId=%r | source_url=%r | source_name=%r | source_slug=%r",
                art_id,
                exc,
                sorted(art.keys()),
                art.get("source_id"),
                art.get("source"),
                art.get("sourceId"),
                art.get("source_url"),
                art.get("source_name"),
                art.get("source_slug"),
            )
            continue

        # Canonicalize source_name from the registry to avoid identity drift.
        resolved_source_id = str(art.get("source_id", "")).strip()
        canonical_source_cfg = ALL_SOURCES.get(resolved_source_id)
        canonical_source_name = ""
        if canonical_source_cfg:
            canonical_source_name = str(canonical_source_cfg.get("name", "")).strip()
            if canonical_source_name:
                incoming_name = str(art.get("source_name", "")).strip()
                if incoming_name != canonical_source_name:
                    logger.warning(
                        "Normalizing source_name for article %s from %r to canonical %r "
                        "(source_id=%s).",
                        art_id,
                        incoming_name or None,
                        canonical_source_name,
                        resolved_source_id,
                    )
                art["source_name"] = canonical_source_name

        # Check if already processed using Main DB
        try:
            numeric_id = int(art_id)
            if not process_id and db_manager.is_article_published(numeric_id):
                continue
        except ValueError:
            # Fallback or skip if ID is not numeric (rare/legacy)
            pass
        articles.append(art)
    return articles


def _select_export_articles(
    cloned_path: Path,
    sibling_path: Path,
    db_manager: DatabaseManager,
    process_id: Optional[str],
    preferred_path: Optional[Path] = None,
) -> tuple[List[Dict[str, Any]], Optional[Path]]:
    selected_path = None
    articles: List[Dict[str, Any]] = []

    if preferred_path:
        if preferred_path.exists():
            logger.info(f"Found Preferred export at {preferred_path}")
            preferred_articles = _load_export_articles(
                preferred_path, db_manager, process_id
            )
            if preferred_articles:
                return preferred_articles, preferred_path
            logger.info(
                "No candidate articles found in preferred export; checking other exports."
            )
        else:
            logger.warning(f"Preferred export path does not exist: {preferred_path}")

    if cloned_path.exists():
        logger.info(f"Found Cloud export at {cloned_path}")
        articles = _load_export_articles(cloned_path, db_manager, process_id)
        selected_path = cloned_path
        if not articles:
            logger.info(
                "No candidate articles found in cloud export; checking local fallback."
            )

    if (not articles) and sibling_path.exists() and sibling_path != cloned_path:
        logger.info(f"Found Local Sibling export at {sibling_path}")
        fallback_articles = _load_export_articles(sibling_path, db_manager, process_id)
        if fallback_articles:
            articles = fallback_articles
            selected_path = sibling_path

    return articles, selected_path


def run_collector_script(
    source_dir: Path, fast_mode: bool = False, dry_run: bool = False
):
    """Runs the news collector direct via API."""
    logger.info(f"Starting News Collector (Direct API)... Dry Run: {dry_run}")

    try:
        # 1. Configuration
        config_override = {}
        if fast_mode:
            logger.info("⚡ FAST MODE: Desactivando análisis cognitivo profundo.")
            config_override["scoring_weights"] = {
                "source_credibility": 0.30,
                "recency": 0.30,
                "content_quality": 0.40,
                "cognitive_engagement": 0.0,
            }

        # 2. Initialize System
        system = create_system(config_override=config_override)

        if not system.initialize():
            logger.error("System initialization failed.")
            return

        # 3. Run Method Wrapper (Async to Sync)
        async def _run_and_export():
            try:
                # Run Collection
                await system.run_collection_cycle(dry_run=dry_run)

                # Export Logic - skip if dry_run? DB dry run generally means no persistence,
                # but we might still want to see what WOULD be exported.
                # Usually collection cycle dry_run returns results but doesn't db save.
                # Let's assume we proceed to export logic if we have results in mem?
                # System.export_articles reads from DB. So dry_run probably yields nothing in DB.

                if not dry_run:
                    target_export_path = (
                        project_root / "data/exports/latest_articles.json"
                    )

                    logger.info(f"Exporting results to {target_export_path}")

                    # Use unified system export
                    await asyncio.to_thread(
                        system.export_latest_articles,
                        file_path=target_export_path,
                        limit=50,
                    )
                else:
                    logger.info("Dry Run: Skipping JSON export (no DB changes).")

            finally:
                if hasattr(system, "shutdown"):
                    await system.shutdown()

        # 4. Handle Execution Loop
        try:
            asyncio.run(_run_and_export())
            logger.info("News Collector finished successfully.")
        except RuntimeError as e:
            if "loop" in str(e).lower():
                # If loop exists (e.g. Streamlit), try to schedule it?
                # Or use run_until_complete if we can access the loop?
                # For now, let's assume standard script execution or thread.
                # If we fail here, we might need nest_asyncio
                logger.error(f"Async loop conflict: {e}")
                raise
            raise

    except Exception as e:
        logger.error(f"Error running collector: {e}")
        import traceback

        traceback.print_exc()


def main(  # noqa: C901
    fetch_only=False,
    process_id=None,
    dev=False,
    skip_visuals=False,
    export_path=None,
    fast_mode=False,
    process_new_content=False,
    dry_run=False,
):
    """
    Main entry point for the Noticiencias Refinery.

    Args:
        fetch_only (bool): If True, only clones/pulls the source repo.
        process_id (str): Optional ID or Title to filter processing.
        dev (bool): If True, enables development features like mock data injection.
        export_path (str): Optional path to a specific JSON export to use.
        dry_run (bool): If True, simulates collection without saving to DB.

    Returns:
        dict: Execution capabilities summary or status.
    """
    logger.info(f"Starting Noticiencias Refinery... (Dry Run={dry_run})")

    try:
        config = load_config()
    except Exception as e:
        logger.critical(f"Config Error: {e}")
        return {"status": "error", "message": str(e)}

    # Initialize Database
    db_manager = DatabaseManager()

    git_handler = GitHubPublisher(config.github.token)
    resolved_models = resolve_ollama_stage_models(config, logger=logger)
    editor_agent = EditorAgent(
        api_url=config.ollama.api_url,
        model=resolved_models["default"],
        translator_model=resolved_models["translator"],
        editor_model=resolved_models["editor"],
        headlines_model=resolved_models["headlines"],
    )

    # Contract Validator to inject into Domain layer
    from news_collector.contracts.collector import CollectorArticleModel

    def validate_collector_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
        return CollectorArticleModel.model_validate(payload).model_dump()

    # Initialize Engine
    engine = RefineryEngine(
        db_manager=db_manager,
        git_handler=git_handler,
        editor_agent=editor_agent,
        config=config,
        contract_validator=validate_collector_payload,
    )

    source_dir = SOURCE_DIR
    preferred_export_path = None
    if export_path:
        preferred_export_path = Path(export_path).expanduser()
    skip_clone = (
        preferred_export_path is not None
        and preferred_export_path.exists()
        and not fetch_only
    )

    # 1. Clone Source Repo
    if skip_clone:
        logger.info(
            f"Skipping source clone; using provided export path: {preferred_export_path}"
        )
    else:
        try:
            source_dir = _safe_clone_source_repo(
                git_handler, config.github.source_repo_url, source_dir
            )
        except Exception as e:
            logger.critical(f"Failed to clone source repo: {e}")
            return {"status": "error", "message": f"Failed to clone source repo: {e}"}

        logger.info("Source data synced successfully.")

    if fetch_only:
        logger.info("Fetch-only mode enabled. Exiting.")
        return {"status": "success", "message": "Source data synced."}

    # 2. Run News Collector (if available) -> Generates new data in SOURCE_DIR/data
    # SKIP if process_id is set (Refine Only Mode) to separate workflows
    if not process_id:
        # Pass dry_run
        run_collector_script(SOURCE_DIR, fast_mode=fast_mode, dry_run=dry_run)
    else:
        logger.info(f"Skipping Collector (Refine Only Mode for ID: {process_id})")

    # Manual Injection for Testing
    data_dir = source_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    # Check if we need to inject a mock file
    # Only if dev mode is enabled
    existing_files = list(data_dir.glob("*.md")) + list(data_dir.glob("*.json"))
    if not existing_files and dev:
        logger.info("Injecting MOCK article for testing (Dev Mode)...")
        mock_file = data_dir / "mock_article.md"
        with open(mock_file, "w", encoding="utf-8") as f:
            f.write(
                "# Breakthrough in Fusion Energy\\n\\nScientists at the National Ignition Facility have achieved net energy gain in a fusion reaction for the second time, proving the viability of this localized star power. The experiment produced 3.15 megajoules of energy from 2.05 megajoules of laser energy delivered to the target."
            )
        logger.info(f"Created mock file: {mock_file}")

    # Find candidate files (md or json)
    # Recursively find files
    articles_to_process = []

    # Check for Collector Export (Primary Source)
    # 1. Look in Cloned Repo (Cloud Source)
    CLONED_EXPORT_PATH = source_dir / "data/exports/latest_articles.json"

    # 2. Look in Sibling Repo (Local Source) - Fallback
    # Load env vars to check for custom path
    from dotenv import dotenv_values

    env_config = dotenv_values(".env")

    # Default relative path
    # In monorepo: apps/refinery/main.py -> root is up 2 levels
    default_sibling_path = Path(__file__).resolve().parents[2]
    # Get from env or default
    collector_path_str = env_config.get(
        "NEWS_COLLECTOR_PATH", str(default_sibling_path)
    )
    collector_path = Path(collector_path_str)

    SIBLING_EXPORT_PATH = collector_path / "data/exports/latest_articles.json"

    selected_export_path = None

    if CLONED_EXPORT_PATH.exists() or SIBLING_EXPORT_PATH.exists():
        articles_to_process, selected_export_path = _select_export_articles(
            CLONED_EXPORT_PATH,
            SIBLING_EXPORT_PATH,
            db_manager,
            process_id,
            preferred_path=preferred_export_path,
        )
        if selected_export_path:
            logger.info(f"Using export at {selected_export_path}")
        logger.info(f"Loaded {len(articles_to_process)} new articles from JSON export.")

    # Fallback / Supplemental: Source Repo Files
    # Priority: Search ONLY in 'data' directory (standard output location)
    # We do NOT fallback to root to avoid picking up repo metadata (labels.md, etc)
    # ONLY load file artifacts if NO export was found OR if we didn't find the requested ID yet
    if not articles_to_process:  # noqa: SIM102
        if data_dir.exists():
            # Files to ignore (exact matches and patterns)
            IGNORED_FILES = {
                "README.md",
                "CHANGELOG.md",
                "CONTRIBUTING.md",
                "SECURITY.md",
                "AGENTS.md",
                "LICENSE",
                "CODE_OF_CONDUCT.md",
                "requirements.txt",
                "labels.md",
                "missing.md",
                "pr_plan.md",
                "Makefile",
                "Dockerfile",
            }

            for ext in ["*.md", "*.json"]:
                for file_path in data_dir.rglob(ext):
                    if file_path.name in IGNORED_FILES:
                        continue
                    if "test" in file_path.parts:
                        continue

                    # Filtering Logic
                    # If process_id is set, we check if filename matches.
                    # Note: filenames might not be IDs, so this is tricky.
                    # We will assume process_id can match filename too.
                    if process_id and process_id not in file_path.name:
                        continue

                    # Check DB
                    if db_manager.is_processed(file_path.name) and not process_id:
                        continue

                    # Read content
                    try:
                        with open(file_path, "r", encoding="utf-8") as f:
                            content = f.read()

                        articles_to_process.append(
                            {
                                "title": file_path.name,
                                "content": content,
                                "source_name": "File System",
                                # Use filename as ID for tracking
                                "id": file_path.name,
                            }
                        )
                    except Exception as e:
                        logger.error(f"Error reading file {file_path}: {e}")

    logger.info(f"Total candidate content items: {len(articles_to_process)}")

    if not articles_to_process:
        if process_id:
            message = (
                f"No se encontraron artículos para el ID solicitado ({process_id})."
            )
        else:
            message = "No se encontraron artículos para procesar."
        if selected_export_path:
            message = f"{message} Export revisado: {selected_export_path}"
        logger.warning(
            f"{message} (process_id={process_id}, "
            f"preferred_export={preferred_export_path}, "
            f"cloud_export_exists={CLONED_EXPORT_PATH.exists()}, "
            f"sibling_export_exists={SIBLING_EXPORT_PATH.exists()})"
        )
        return {"status": "noop", "message": message, "processed_count": 0}

    # Update: If process_id is set, we expect EXACTLY 1 item usually, but list is fine.
    # If NO process_id is set (Bulk Mode), we might want to LIMIT for safety or testing.
    if not process_id and articles_to_process:
        # LIMIT FOR BULK MODE: Process only the first items to avoid infinite loops or costs
        # User requested manual selection anyway, so bulk mode might arguably just process 1 or 5.
        limit = 5
        articles_to_process = articles_to_process[:limit]
        logger.info(f"BULK MODE: Limiting to first {limit} item(s)")

    if not process_new_content and not process_id:
        logger.info("Auto-processing disabled. New articles saved to inbox.")
        return {
            "status": "success",
            "message": f"{len(articles_to_process)} articles collected. Ready for review.",
            "processed_count": 0,
        }

    last_error = None
    processed_count = 0

    # Initialize Target Repo (Clone if needed)
    target_repo_obj = None
    try:
        if TARGET_DIR.exists():
            shutil.rmtree(TARGET_DIR, ignore_errors=True)

        logger.info(f"Cloning Target Repo: {config.github.target_repo_url}")
        git_handler.clone_repo(config.github.target_repo_url, TARGET_DIR)
        target_repo_obj = git.Repo(TARGET_DIR)

        # Configure User
        with target_repo_obj.config_writer() as git_config:
            git_config.set_value("user", "name", config.github.user_name)
            git_config.set_value("user", "email", config.github.user_email)

    except Exception as e:
        logger.critical(f"Failed to clone/init target repo: {e}")
        return {
            "status": "error",
            "message": f"Critical Git Error: {e}",
            "processed_count": 0,
        }

    try:
        if articles_to_process:
            summary = engine.process_articles(
                articles_to_process, target_repo_obj, TARGET_DIR
            )
            processed_count = summary["processed_count"]
            if summary["errors"]:
                last_error = str(summary["errors"][-1])
                logger.warning(f"Engine reported {len(summary['errors'])} errors.")
    except Exception as e:
        logger.error(f"Engine execution failed: {e}")
        return {
            "status": "error",
            "message": f"Engine failed: {e}",
            "processed_count": 0,
        }

    except KeyboardInterrupt:
        logger.warning("\n\nRefinery stopped by user (Ctrl+C). Exiting gracefully...")
        return {"status": "cancelled", "processed_count": processed_count}

    logger.info("Refinery pass complete.")

    if processed_count == 0 and last_error:
        return {
            "status": "error",
            "message": f"Error procesando artículo: {last_error}",
            "processed_count": 0,
        }

    return {"status": "success", "processed_count": processed_count}


def delete_article(article_id: str) -> dict:
    """
    Locates and deletes an article from the target repo based on its refinery_id.
    Creates a Pull Request for the deletion.
    """
    logger.info(f"Initiating One-Click Unpublish for ID: {article_id}")

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

        if posts_dir.exists():
            for file_path in posts_dir.glob("*.md"):
                try:
                    content = file_path.read_text(encoding="utf-8")
                    if f'refinery_id: "{article_id}"' in content:
                        target_file = file_path
                        break
                except Exception:  # noqa: S112
                    continue

        if not target_file:
            logger.warning(f"Article ID {article_id} not found in published content.")
            return {
                "status": "error",
                "message": "Article not found in remote content.",
            }

        # 3. Create Branch
        branch_name = git_handler.create_branch(
            target_repo_obj, branch_prefix="delete/article"
        )

        # 4. Delete File
        filename = target_file.name
        target_file.unlink()
        logger.info(f"Deleted file: {filename}")

        # 5. Commit & Push
        git_handler.commit_and_push(
            target_repo_obj, f"Unpublish article: {filename}", branch_name
        )

        # 6. Create PR
        pr_url = git_handler.create_pull_request(
            repo_url=config.github.target_repo_url,
            branch_name=branch_name,
            title=f"Unpublish: {filename}",
            body=f"Request to unpublish/delete {filename}.\n\nRefinery ID: {article_id}",
        )

        return {"status": "success", "pr_url": pr_url, "file_name": filename}

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
        dev=args.dev,
        skip_visuals=args.skip_visuals,
        export_path=args.export_path,
    )
