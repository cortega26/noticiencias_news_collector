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


def main(fetch_only=False, process_id=None, dev=False):
    """
    Main entry point for the Noticiencias Refinery.
    
    Args:
        fetch_only (bool): If True, only clones/pulls the source repo.
        process_id (str): Optional ID or Title to filter processing.
        dev (bool): If True, enables development features like mock data injection.
        
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
    
    # 1. Clone Source Repo
    try:
        # Cleanup source dir manually to ensure clean state
        if SOURCE_DIR.exists():
            shutil.rmtree(SOURCE_DIR, ignore_errors=True)
            
        git_handler.clone_repo(config.SOURCE_REPO_URL, SOURCE_DIR)
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
    data_dir = SOURCE_DIR / "data"
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
    CLONED_EXPORT_PATH = SOURCE_DIR / "data/exports/latest_articles.json"
    
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
    
    COLLECTOR_EXPORT_PATH = None
    
    if CLONED_EXPORT_PATH.exists():
         COLLECTOR_EXPORT_PATH = CLONED_EXPORT_PATH
         logger.info(f"Found Cloud export at {COLLECTOR_EXPORT_PATH}")
    elif SIBLING_EXPORT_PATH.exists():
         COLLECTOR_EXPORT_PATH = SIBLING_EXPORT_PATH
         logger.info(f"Found Local Sibling export at {COLLECTOR_EXPORT_PATH}")
    
    if COLLECTOR_EXPORT_PATH and COLLECTOR_EXPORT_PATH.exists():
        try:
            with open(COLLECTOR_EXPORT_PATH, "r", encoding="utf-8") as f:
                header_articles = json.load(f)
                
            # Convert to internal format if needed, but they should match what EditorAgent expects
            # We filter for top scoring or recent ones if needed, but the file is already "latest"
            for art in header_articles:
                # Use ID or Title as key for processed check
                art_id = str(art.get("id", art.get("title")))
                
                # If specific ID requested, verify match
                if process_id and str(art_id) != str(process_id):
                    continue
                    
                if db_manager.is_processed(art_id) and not process_id:
                    # Skip processed ONLY if we are running in auto mode. 
                    # If specific ID is requested, we assume USER wants to force re-process.
                    continue
                    
                articles_to_process.append(art)
                
            logger.info(f"Loaded {len(articles_to_process)} new articles from JSON export.")
        except Exception as e:
            logger.error(f"Failed to load collector export: {e}")

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
    args = parser.parse_args()

    main(fetch_only=args.fetch_only, process_id=args.process_id, dev=args.dev)
