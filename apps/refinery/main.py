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
from src.utils.config import load_config
from src.utils.logger import setup_logger
from src.services.git_service import GitHandler
from src.services.editor_agent import EditorAgent
from src.database import DatabaseManager

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


def _safe_clone_source_repo(
    git_handler: GitHandler,
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

    articles = []
    for art in header_articles:
        art_id = str(art.get("id", art.get("title")))
        if process_id and str(art_id) != str(process_id):
            continue
        if db_manager.is_processed(art_id) and not process_id:
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


def main(fetch_only=False, process_id=None, dev=False, skip_visuals=False, export_path=None):
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

    git_handler = GitHandler(config.GITHUB_TOKEN)
    editor_agent = EditorAgent(config.OLLAMA_API_URL, config.OLLAMA_MODEL)

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
                git_handler, config.SOURCE_REPO_URL, source_dir
            )
        except Exception as e:
            logger.critical(f"Failed to clone source repo: {e}")
            return {"status": "error", "message": f"Failed to clone source repo: {e}"}

        logger.info("Source data synced successfully.")
    
    if fetch_only:
        logger.info("Fetch-only mode enabled. Exiting.")
        return {"status": "success", "message": "Source data synced."}

    # 2. Run News Collector (if available) -> Generates new data in SOURCE_DIR/data
    # SKIP COLLECTOR FOR TESTING (avoid dependency issues)
    # run_collector_script(SOURCE_DIR)

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

    processed_count = 0
    try:
        for article in articles_to_process:
            # Identifier
            article_id = str(article.get("id", article.get("title")))
            file_name = f"{article_id}.md" # logical filename for logs
            
            logger.info(f"Processing item: {article_id}")
            
            try:
                # 2. Process with LLM
                # Pass the WHOLE article dict (or constructed dict for files)
                refined_content = editor_agent.process_article(article)

                # 2.5 Visual Analysis (Optional)
                if not skip_visuals:
                    logger.info("🎨 Running Visual Analysis...")
                    visual_data = editor_agent.analyze_visuals(refined_content)
                    
                    # Inject into Frontmatter
                    # We look for the ending "---" of the frontmatter
                    # Assuming standard frontmatter format
                    frontmatter_end_idx = refined_content.find("---", 3)
                    if frontmatter_end_idx != -1:
                        # Construct YAML block
                        visual_yaml = (
                            f"visual_category: {visual_data.get('visual_category', 'OTHER')}\n"
                            f"visual_keywords: {json.dumps(visual_data.get('visual_keywords', []))}\n"
                            f"visual_prompt: \"{visual_data.get('visual_prompt', '')}\"\n"
                        )
                        # Insert before the closing ---
                        refined_content = (
                            refined_content[:frontmatter_end_idx] 
                            + visual_yaml 
                            + refined_content[frontmatter_end_idx:]
                        )
                        logger.info(f"Visual metadata injected: {visual_data.get('visual_category')}")
                else:
                    logger.info("Skipping Visual Analysis as requested.")
                
                # 3. Prepare Target Repo (Clone fresh to ensure clean state for branching)
                # target_repo = None # Unused
                if TARGET_DIR.exists():
                     shutil.rmtree(TARGET_DIR, ignore_errors=True)
                     
                git_handler.clone_repo(config.TARGET_REPO_URL, TARGET_DIR)
                target_repo_obj = git.Repo(TARGET_DIR)
                
                # 4. Create Branch
                branch_name = git_handler.create_branch(target_repo_obj)
                
                # 5. Save content
                # Changed to _posts for Jekyll compatibility
                posts_dir = TARGET_DIR / "_posts"
                posts_dir.mkdir(parents=True, exist_ok=True)
                
                # Parse metadata for filename convention: YYYY-MM-DD-title.md
                today_str = datetime.now().strftime("%Y-%m-%d")
                
                # FORCE DATE TO TODAY (System Time) to ensure visibility on the site
                date_str = today_str
                
                # Patch the content with the real date
                refined_content = re.sub(
                    r'^date:\s*["\']?(\d{4}-\d{2}-\d{2})["\']?', 
                    f'date: {today_str}', 
                    refined_content, 
                    flags=re.MULTILINE
                )
                
                title_slug = "sin-titulo"
                
                # Extract and slugify title
                title_match = re.search(r'^title:\s*["\']?([^\r\n"\']+)["\']?', refined_content, re.MULTILINE)
                if title_match:
                    raw_title = title_match.group(1).strip()
                    
                    # Simple accent mapping for cleaner slugs
                    accents = {
                        'á': 'a', 'é': 'e', 'í': 'i', 'ó': 'o', 'ú': 'u', 'ü': 'u', 'ñ': 'n',
                        'Á': 'a', 'É': 'e', 'Í': 'i', 'Ó': 'o', 'Ú': 'u', 'Ü': 'u', 'Ñ': 'n'
                    }
                    clean_title = raw_title.lower()
                    for char, replacement in accents.items():
                        clean_title = clean_title.replace(char, replacement)
                    
                    # Slugify
                    title_slug = re.sub(r'[^a-z0-9]+', '-', clean_title).strip('-')
                
                # Truncate
                if len(title_slug) > 100:
                    title_slug = title_slug[:100]
                
                if not title_slug or len(title_slug) < 2:
                     title_slug = f"articulo-{uuid.uuid4().hex[:6]}"

                output_filename = f"{date_str}-{title_slug}.md"
                output_path = posts_dir / output_filename
                
                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write(refined_content)
                    
                logger.info(f"Saved refined article to {output_path}")
                
                # LOGGING FOR DEBUGGING
                expected_url = f"https://noticiencias.com/{title_slug}/"
                logger.info(f"🔍 DEBUG TRACE: Expected Public URL -> {expected_url}")

                # --- NEW: Generate Social Media Drafts ---
                try:
                    logger.info("Generating Social Media Drafts...")
                    # Simulating the future URL (assuming standard Jekyll structure)
                    # We strip the date for the slug check just to be safe, or just use the filename
                    # Date is YYYY-MM-DD-slug.md
                    slug = output_filename.replace(".md", "")
                    # Remove date prefix if present (simple heuristic)
                    parts = slug.split("-")
                    if len(parts) > 3 and parts[0].isdigit():
                         slug = "-".join(parts[3:])
                         
                    post_url = f"https://noticiencias.com/posts/{slug}"
                    social_text = editor_agent.generate_social_content(refined_content, url=post_url)
                    
                    logger.info("\n" + "="*40 + "\n📱 SOCIAL MEDIA DRAFTS 📱\n" + "="*40 + "\n" + social_text + "\n" + "="*40 + "\n")
                except Exception as e:
                    logger.error(f"Failed to generate social media content: {e}")
                # ----------------------------------------
                
                # 6. Commit and Push
                git_handler.commit_and_push(target_repo_obj, f"Add article: {file_name}", branch_name)
                
                # 7. Create PR
                pr_url = git_handler.create_pull_request(
                    repo_url=config.TARGET_REPO_URL,
                    branch_name=branch_name,
                    title=f"News: {date_str} - {title_slug}",
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
                
    except KeyboardInterrupt:
        logger.warning("\n\nRefinery stopped by user (Ctrl+C). Exiting gracefully...")
        return {"status": "cancelled", "processed_count": processed_count}

    logger.info("Refinery pass complete.")
    return {"status": "success", "processed_count": processed_count}


if __name__ == "__main__":
    import git
    import shutil # Need to ensure imports are present if we use them
    
    parser = argparse.ArgumentParser(description="Noticiencias Refinery Orchestrator")
    parser.add_argument("--fetch-only", action="store_true", help="Only clone/pull source repo, do not process articles.")
    parser.add_argument("--process-id", type=str, help="Process a specific article ID (or title) only.")
    parser.add_argument("--dev", action="store_true", help="Enable development features (like mock generation).")
    parser.add_argument("--skip-visuals", action="store_true", help="Skip the visual analysis step (faster).")
    parser.add_argument("--export-path", type=str, help="Optional JSON export path to use.")
    args = parser.parse_args()

    main(
        fetch_only=args.fetch_only,
        process_id=args.process_id,
        dev=args.dev,
        skip_visuals=args.skip_visuals,
        export_path=args.export_path,
    )
