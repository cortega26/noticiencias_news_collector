import argparse
import json
import logging
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
import yaml

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from news_collector.logic.parsers.image_extractor import ImageExtractor
from news_collector.infrastructure.requests_client import RobustRequestsClient

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("ImageRepair")

POSTS_DIR = Path("../noticiencias/src/content/posts").resolve()
ASSETS_DIR = Path("../noticiencias/src/assets/images").resolve()

# Regex for frontmatter
# Supports YAML using --- delimiters
FRONTMATTER_PATTERN = re.compile(r"^---\n(.*?)\n---", re.DOTALL)

class RepairStats:
    def __init__(self):
        self.total_scanned = 0
        self.candidates = 0
        self.skipped_mock = 0
        self.skipped_ok = 0
        self.skipped_ambiguous = 0
        self.repaired = 0
        self.failed = 0
        self.repaired_ids = []
        self.failed_ids = []

    def to_dict(self):
        return {
            "total_scanned": self.total_scanned,
            "candidates": self.candidates,
            "skipped_mock": self.skipped_mock,
            "skipped_ok": self.skipped_ok,
            "skipped_ambiguous": self.skipped_ambiguous,
            "repaired": self.repaired,
            "failed": self.failed,
            "repaired_ids": self.repaired_ids,
            "failed_ids": self.failed_ids,
        }

def parse_frontmatter(content: str) -> Optional[Dict[str, Any]]:
    match = FRONTMATTER_PATTERN.match(content)
    if not match:
        return None
    try:
        return yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        return None

def is_mock_article(fm: Dict[str, Any]) -> bool:
    # Rule: Mock if missing `refinery_id` AND `source_url`
    has_refinery = bool(fm.get("refinery_id"))
    has_source = bool(fm.get("source_url"))
    
    if not has_refinery and not has_source:
        return True
    return False

def has_valid_image(fm: Dict[str, Any]) -> bool:
    image = fm.get("image")
    if not image:
        return False
    
    # If it's a string
    if isinstance(image, str):
        if not image.strip():
            return False
        if image.startswith("http"):
            return False # Needs repair (download)
        
    # Check if local file exists
    # Expected format: ~/assets/images/filename.jpg
    if image.startswith("~/assets/images/"):
        rel_path = image.replace("~/assets/images/", "")
        full_path = ASSETS_DIR / rel_path
        if full_path.exists() and full_path.stat().st_size > 0:
            return True
        else:
            return False # File missing

    # Check for legacy public/ images
    # e.g. /images/foo.png -> ../noticiencias/public/images/foo.png
    if image.startswith("/"):
        # Assumption: public is at ../noticiencias/public
        public_dir = Path("../noticiencias/public").resolve()
        # image is redundant slash, e.g. /images/foo.png
        # so public_dir / images / foo.png
        # remove leading slash
        rel_path = image.lstrip("/")
        full_path = public_dir / rel_path
        if full_path.exists() and full_path.stat().st_size > 0:
            return True
        else:
            return False # File missing in public

    return False # Unknown format or empty

def download_image(url: str, slug: str, dry_run: bool) -> Optional[str]:
    """Downloads image and returns Astro path (~/assets/images/...)"""
    if not url or not url.startswith("http"):
        return None

    # Determine extension
    ext = ".jpg" # default
    if ".png" in url.lower():
        ext = ".png"
    elif ".webp" in url.lower():
        ext = ".webp"
    elif ".jpeg" in url.lower():
        ext = ".jpg"
    elif ".gif" in url.lower():
        ext = ".gif"

    filename = f"{slug}{ext}"
    local_path = ASSETS_DIR / filename
    
    # Check if already exists (Idempotency)
    if local_path.exists() and local_path.stat().st_size > 0:
        logger.info(f"Image already exists: {local_path}")
        return f"~/assets/images/{filename}"

    if dry_run:
        logger.info(f"[DRY RUN] Would download {url} to {local_path}")
        return f"~/assets/images/{filename}"

    try:
        ASSETS_DIR.mkdir(parents=True, exist_ok=True)
        with RobustRequestsClient() as client:
            response = client.get(url, timeout=15)
            # Basic validation
            if response.status_code == 200 and len(response.content) > 1000:
                local_path.write_bytes(response.content)
                logger.info(f"Downloaded image: {local_path}")
                return f"~/assets/images/{filename}"
            else:
                logger.warning(f"Failed download or small file: {url} ({response.status_code})")
                return None
    except Exception as e:
        logger.error(f"Error downloading {url}: {e}")
        return None

def extract_best_image_url(source_url: str) -> Optional[str]:
    if not source_url:
        return None
    
    logger.info(f"Scraping {source_url} for og:image...")
    try:
        extractor = ImageExtractor()
        with RobustRequestsClient() as client:
            resp = client.get(source_url, timeout=15)
            if resp.status_code != 200:
                return None
            
            candidates = extractor.extract_candidates(resp.text, source_url)
            if candidates:
                for cand in candidates:
                    if extractor.validate_image(cand):
                        return cand.url
    except Exception as e:
        logger.warning(f"Extraction failed for {source_url}: {e}")
    
    return None

def fix_corrupted_frontmatter(file_path: Path):
    content = file_path.read_text(encoding="utf-8")
    # Fix missing newline before closing ---
    # Pattern: [not newline]---
    if re.search(r"[^\n]---", content):
        logger.warning(f"Fixing corrupted frontmatter in {file_path.name}")
        # Insert newline before ---
        new_content = re.sub(r"([^\n])---", r"\1\n---", content, count=1)
        file_path.write_text(new_content, encoding="utf-8")
        return True
    return False

def update_markdown(file_path: Path, new_image_path: str, dry_run: bool):
    content = file_path.read_text(encoding="utf-8")
    
    match = FRONTMATTER_PATTERN.match(content)
    if not match:
        return False
        
    fm_str = match.group(1)
    
    # Check if image key exists
    if re.search(r"^image:", fm_str, re.MULTILINE):
        # Replace existing
        new_fm_str = re.sub(r"^image:.*$", f"image: \"{new_image_path}\"", fm_str, flags=re.MULTILINE)
    else:
        # Append to end of frontmatter
        new_fm_str = fm_str.strip() + f"\nimage: \"{new_image_path}\"\n"
        
    # Ensure newline before closing ---
    new_content = f"---\n{new_fm_str.strip()}\n---" + content[match.end():]
    
    if dry_run:
        logger.info(f"[DRY RUN] Would update {file_path}")
        return True
        
    file_path.write_text(new_content, encoding="utf-8")
    return True

def main():
    parser = argparse.ArgumentParser(description="Repair missing images in noticiencias articles")
    parser.add_argument("--dry-run", action="store_true", help="Scan only, do not write changes")
    args = parser.parse_args()

    stats = RepairStats()
    
    if not POSTS_DIR.exists():
        logger.error(f"Posts directory not found: {POSTS_DIR}")
        sys.exit(1)

    files = sorted(list(POSTS_DIR.glob("*.md")))
    logger.info(f"Scanning {len(files)} files in {POSTS_DIR}...")

    for file_path in files:
        stats.total_scanned += 1
        try:
            # Pre-fix corruption if any
            fix_corrupted_frontmatter(file_path)

            content = file_path.read_text(encoding="utf-8")
            fm = parse_frontmatter(content)
            
            if not fm:
                logger.warning(f"Could not parse frontmatter: {file_path.name}")
                stats.skipped_ambiguous += 1
                continue

            # 1. Check if Mock
            if is_mock_article(fm):
                stats.skipped_mock += 1
                continue

            # 2. Check if valid image
            if has_valid_image(fm):
                stats.skipped_ok += 1
                continue

            # 3. Candidate for repair
            stats.candidates += 1
            logger.info(f"Candidate found: {file_path.name}")
            
            image_url_to_download = None
            
            current_image = fm.get("image")
            if isinstance(current_image, str) and current_image.startswith("http"):
                image_url_to_download = current_image
                logger.info(f"  -> Using existing remote URL: {image_url_to_download}")
            
            if not image_url_to_download:
                source_url = fm.get("source_url")
                if source_url:
                    logger.info(f"  -> Attempting extraction from: {source_url}")
                    extracted = extract_best_image_url(source_url)
                    if extracted:
                        image_url_to_download = extracted
                        logger.info(f"  -> Extracted: {image_url_to_download}")
            
            if image_url_to_download:
                slug = file_path.stem
                
                local_ref = download_image(image_url_to_download, slug, args.dry_run)
                if local_ref:
                    if update_markdown(file_path, local_ref, args.dry_run):
                        stats.repaired += 1
                        stats.repaired_ids.append(file_path.name)
                        logger.info(f"  -> REPAIRED: {file_path.name}")
                    else:
                        stats.failed += 1
                        stats.failed_ids.append({"id": file_path.name, "reason": "Markdown update failed"})
                else:
                    stats.failed += 1
                    stats.failed_ids.append({"id": file_path.name, "reason": "Download failed"})
            else:
                stats.failed += 1
                stats.failed_ids.append({"id": file_path.name, "reason": "No image source available"})

        except Exception as e:
            logger.error(f"Error processing {file_path.name}: {e}")
            stats.failed += 1
            stats.failed_ids.append({"id": file_path.name, "reason": str(e)})

    # Report
    report = {
        "discovered_contract": {
            "image_storage_dir": str(ASSETS_DIR),
            "image_reference_format": "~/assets/images/...",
            "article_image_fields": ["image"],
            "downloader_entrypoints": ["RefineryEngine._download_image", "RepairScript"]
        },
        "scan": {
            "total_scanned": stats.total_scanned,
            "candidates": stats.candidates,
            "skipped_mock": stats.skipped_mock,
            "skipped_ok": stats.skipped_ok,
            "skipped_ambiguous": stats.skipped_ambiguous
        },
        "results": {
            "repaired": stats.repaired,
            "failed": stats.failed,
            "repaired_ids": stats.repaired_ids,
            "failed_ids": stats.failed_ids
        }
    }
    
    print(json.dumps(report, indent=2))
    
    with open("repair_report.json", "w") as f:
        json.dump(report, f, indent=2)

if __name__ == "__main__":
    main()
