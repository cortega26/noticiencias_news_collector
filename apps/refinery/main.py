import json
import argparse
import shutil
import os
import glob
import uuid
import sys
import subprocess
from pathlib import Path
import git
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

# Add project root to sys.path to allow imports if running standalone or via streamlit
project_root = Path(__file__).resolve().parents[2]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from noticiencias.config_manager import load_config
from src.utils.logger import setup_logger
from news_collector.components.publishing import GitHubPublisher
from news_collector.components.editorial import EditorAgent
# from news_collector.components.editorial import EditorAgent # Removed duplicate
from src.database import DatabaseManager

from news_collector.system import create_system
import asyncio
from datetime import timezone


logger = setup_logger("Orchestrator")

PROCESSED_LOG_FILE = "processed_log.json"
TEMP_DIR = Path("temp")
SOURCE_DIR = TEMP_DIR / "source"
TARGET_DIR = TEMP_DIR / "target"
DB_PATH = Path("refinery.db")

def _is_file_lock_error(exc: Exception) -> bool:
    winerror = getattr(exc, "winerror", None)
    if winerror == 32:
        return True
    message = str(exc).lower()
    return "being used by another process" in message or "utilizado por otro proceso" in message


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

def _load_export_articles(
    export_path: Path,
    db_manager: DatabaseManager,
    process_id: Optional[str],
) -> List[Dict[str, Any]]:
    try:
        with open(export_path, "r", encoding="utf-8") as f:
            header_articles = json.load(f)
    except Exception as exc:
        logger.error(f"Failed to load collector export at {export_path}: {exc}")
        return []

    if isinstance(header_articles, dict):
        header_articles = header_articles.get("articles", [])
    if not isinstance(header_articles, list):
        logger.error(
            f"Export payload has unexpected format at {export_path}: {type(header_articles)}"
        )
        return []

    articles = []
    for art in header_articles:
        art_id = str(art.get("id", art.get("title")))
        if process_id and str(art_id) != str(process_id):
            continue
        if (
            not process_id
            and (
                db_manager.is_processed(art_id)
                or db_manager.is_processed(f"{art_id}.md")
            )
        ):
            continue
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
        fallback_articles = _load_export_articles(
            sibling_path, db_manager, process_id
        )
        if fallback_articles:
            articles = fallback_articles
            selected_path = sibling_path

    return articles, selected_path


def run_collector_script(source_dir: Path, fast_mode: bool = False):
    """Runs the news collector direct via API."""
    logger.info("Starting News Collector (Direct API)...")
    
    try:
        # 1. Configuration
        config_override = {}
        if fast_mode:
             logger.info("⚡ FAST MODE: Desactivando análisis cognitivo profundo.")
             config_override["scoring_weights"] = {
                 "source_credibility": 0.30,
                 "recency": 0.30,
                 "content_quality": 0.40,
                 "cognitive_engagement": 0.0 
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
                 await system.run_collection_cycle(dry_run=False)
                 
                 # Export Logic (Shared with run_collector.py)
                 export_path = Path("data/exports/latest_articles.json") # Relative to CWD (root)
                 
                 # We will try to write to the standard location relative to project root
                 target_export_path = project_root / "data/exports/latest_articles.json"
                 target_export_path.parent.mkdir(parents=True, exist_ok=True)
                 
                 logger.info(f"Exporting results to {target_export_path}")
                 
                 # Get articles
                 articles = await asyncio.to_thread(
                     system.db_manager.get_articles_by_score, limit=50, exclude_published=True
                 )
                 
                 serialized_articles = []
                 for art in articles:
                    art_dict = {
                        "id": art.id,
                        "title": art.title,
                        "url": art.url,
                        "summary": art.summary,
                        "content": art.content,
                        "source_name": art.source_name,
                        "published_date": art.published_date.isoformat() if art.published_date else None,
                        "published_at": art.published_at.isoformat() if getattr(art, "published_at", None) else None,
                        "published_url": getattr(art, "published_url", None),
                        "collected_date": art.collected_date.isoformat() if art.collected_date else None,
                        "score": art.final_score,
                        "image_url": art.article_metadata.get("image_url") if art.article_metadata else None,
                        "metadata": art.article_metadata,
                        "authors": art.authors,
                        "category": art.category,
                        "components": art.score_components or {}
                    }
                    serialized_articles.append(art_dict)
                
                 export_payload = {
                    "schema_version": 1,
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "contract": "news_collector.export.v1",
                    "article_count": len(serialized_articles),
                    "articles": serialized_articles,
                 }

                 with open(target_export_path, 'w', encoding='utf-8') as f:
                    json.dump(export_payload, f, indent=2, ensure_ascii=False)
                    
             finally:
                 if hasattr(system, 'shutdown'):
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


def main(fetch_only=False, process_id=None, dev=False, skip_visuals=False, export_path=None, fast_mode=False, process_new_content=False):
    """
    Main entry point for the Noticiencias Refinery.
    
    Args:
        fetch_only (bool): If True, only clones/pulls the source repo.
        process_id (str): Optional ID or Title to filter processing.
        dev (bool): If True, enables development features like mock data injection.
        export_path (str): Optional path to a specific JSON export to use.
        
    Returns:
        dict: Execution capabilities summary or status.
    """
    logger.info("Starting Noticiencias Refinery...")
    
    try:
        config = load_config()
    except Exception as e:
        logger.critical(f"Config Error: {e}")
        return {"status": "error", "message": str(e)}

    # Initialize Database
    db_manager = DatabaseManager(DB_PATH)

    git_handler = GitHubPublisher(config.github.token)
    editor_agent = EditorAgent(config.ollama.api_url, config.ollama.model)

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
        run_collector_script(SOURCE_DIR, fast_mode=fast_mode)
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
            f.write("# Breakthrough in Fusion Energy\\n\\nScientists at the National Ignition Facility have achieved net energy gain in a fusion reaction for the second time, proving the viability of this localized star power. The experiment produced 3.15 megajoules of energy from 2.05 megajoules of laser energy delivered to the target.")
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
    collector_path_str = env_config.get("NEWS_COLLECTOR_PATH", str(default_sibling_path))
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
        logger.info(
            f"Loaded {len(articles_to_process)} new articles from JSON export."
        )

    # Fallback / Supplemental: Source Repo Files
    # Priority: Search ONLY in 'data' directory (standard output location)
    # We do NOT fallback to root to avoid picking up repo metadata (labels.md, etc)
    # ONLY load file artifacts if NO export was found OR if we didn't find the requested ID yet
    if not articles_to_process:
        if data_dir.exists():
            # Files to ignore (exact matches and patterns)
            IGNORED_FILES = {
                'README.md', 'CHANGELOG.md', 'CONTRIBUTING.md', 'SECURITY.md', 
                'AGENTS.md', 'LICENSE', 'CODE_OF_CONDUCT.md', 'requirements.txt',
                'labels.md', 'missing.md', 'pr_plan.md', 'Makefile', 'Dockerfile'
            }
            
            for ext in ['*.md', '*.json']:
                for file_path in data_dir.rglob(ext):
                    if file_path.name in IGNORED_FILES: continue
                    if 'test' in file_path.parts: continue
                    
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
                        with open(file_path, 'r', encoding='utf-8') as f:
                            content = f.read()
                        
                        articles_to_process.append({
                            "title": file_path.name,
                            "content": content,
                            "source_name": "File System",
                             # Use filename as ID for tracking
                            "id": file_path.name
                        })
                    except Exception as e:
                        logger.error(f"Error reading file {file_path}: {e}")
    
    logger.info(f"Total candidate content items: {len(articles_to_process)}")

    if not articles_to_process:
        if process_id:
            message = f"No se encontraron artículos para el ID solicitado ({process_id})."
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
        return {"status": "success", "message": f"{len(articles_to_process)} articles collected. Ready for review.", "processed_count": 0}

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
        return {"status": "error", "message": f"Critical Git Error: {e}", "processed_count": 0}

    try:
        for article in articles_to_process:
            # Identifier
            article_id = str(article.get("id", article.get("title")))
            file_name = f"{article_id}.md" # logical filename for logs
            branch_name = None # Initialize to avoid UnboundLocalError
            
            logger.info(f"Processing item: {article_id} (Version: Restored Logic)")
            
            try:
                # ... (inner logic) ...
                
                # 2. Process with LLM
                refined_content = editor_agent.process_article(article)
                
                # 3. Determine Output Filename
                date_str = datetime.now().strftime("%Y-%m-%d")
                
                # Try to extract slug from frontmatter
                output_slug = f"article-{article_id}"
                if "slug:" in refined_content:
                    try:
                        import re
                        match = re.search(r'slug:\s*"?([^"\n]+)"?', refined_content)
                        if match:
                            output_slug = match.group(1).strip()
                    except:
                        pass
                
                output_filename = f"{date_str}-{output_slug}.md"
                
                # 4. Save to Target Repo structure
                # Ensure structure exists: src/content/posts
                posts_path = TARGET_DIR / "src/content/posts"
                posts_path.mkdir(parents=True, exist_ok=True)
                
                target_file_path = posts_path / output_filename
                with open(target_file_path, "w", encoding="utf-8") as f:
                    f.write(refined_content)
                
                logger.info(f"Written content to {target_file_path}")

                # 5. Create Branch
                branch_name = git_handler.create_branch(target_repo_obj, branch_prefix="content/add")

                # 6. Commit and Push
                git_handler.commit_and_push(target_repo_obj, f"Add article: {output_filename}", branch_name)
                
                # 7. Create PR
                pr_url = git_handler.create_pull_request(
                    repo_url=config.github.target_repo_url,
                    branch_name=branch_name,
                    title=f"News: {date_str} - {output_slug}",
                    body=f"Automated submission for {file_name}.\n\nProcessed by Noticiencias Refinery."
                )
                
                if pr_url:
                    logger.info(f"Pull Request created successfully: {pr_url}")
                    # MARK AS PROCESSED IN DB
                    db_manager.mark_processed(file_name)
                    processed_count += 1
                else:
                    logger.error("Failed to create PR.")
            
            except Exception as e:
                logger.error(f"Failed to process {file_name}: {e}")
                last_error = str(e)
                
    except KeyboardInterrupt:
        logger.warning("\n\nRefinery stopped by user (Ctrl+C). Exiting gracefully...")
        return {"status": "cancelled", "processed_count": processed_count}

    logger.info("Refinery pass complete.")
    
    if processed_count == 0 and last_error:
         return {"status": "error", "message": f"Error procesando artículo: {last_error}", "processed_count": 0}
         
    return {"status": "success", "processed_count": processed_count}

def delete_article(article_id: str) -> dict:
    """
    Locates and deletes an article from the target repo based on its refinery_id.
    Creates a Pull Request for the deletion.
    """
    logger.info(f"Initiating One-Click Unpublish for ID: {article_id}")
    
    try:
        config = load_config()
        git_handler = GitHubPublisher(config.github.token)
        
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
                except:
                    continue
        
        if not target_file:
            logger.warning(f"Article ID {article_id} not found in published content.")
            return {"status": "error", "message": "Article not found in remote content."}
            
        # 3. Create Branch
        branch_name = git_handler.create_branch(target_repo_obj, branch_prefix="delete/article")
        
        # 4. Delete File
        filename = target_file.name
        target_file.unlink()
        logger.info(f"Deleted file: {filename}")
        
        # 5. Commit & Push
        git_handler.commit_and_push(target_repo_obj, f"Unpublish article: {filename}", branch_name)
        
        # 6. Create PR
        pr_url = git_handler.create_pull_request(
            repo_url=config.github.target_repo_url,
            branch_name=branch_name,
            title=f"Unpublish: {filename}",
            body=f"Request to unpublish/delete {filename}.\n\nRefinery ID: {article_id}"
        )
        
        return {"status": "success", "pr_url": pr_url, "file_name": filename}

    except Exception as e:
        logger.error(f"Failed to delete article: {e}")
        return {"status": "error", "message": str(e)}


if __name__ == "__main__":
    import git
    import shutil # Need to ensure imports are present if we use them
    
    parser = argparse.ArgumentParser(description="Noticiencias Refinery Orchestrator")
    parser.add_argument("--fetch-only", action="store_true", help="Only clone/pull source repo, do not process articles.")
    parser.add_argument("--process-id", type=str, help="Process a specific article ID (or title) only.")
    parser.add_argument("--dev", action="store_true", help="Enable development features (like mock generation).")
    parser.add_argument("--skip-visuals", action="store_true", help="Skip the visual analysis step (faster).")
    parser.add_argument("--delete-id", type=str, help="Unpublish/Delete a specific article ID.")
    args = parser.parse_args()

    if args.delete_id:
        result = delete_article(args.delete_id)
        print(json.dumps(result)) # Output for caller
        sys.exit(0 if result["status"] == "success" else 1)

    main(
        fetch_only=args.fetch_only,
        process_id=args.process_id,
        dev=args.dev,
        skip_visuals=args.skip_visuals,
        export_path=args.export_path,
    )
