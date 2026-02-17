
import os
import shutil
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("migrate_db")

LEGACY_DB_PATH = "data/enrichment_metrics.db"
NEW_BASE_DIR = "data/metrics"

def migrate():
    if not os.path.exists(LEGACY_DB_PATH):
        logger.info(f"No legacy DB found at {LEGACY_DB_PATH}. Nothing to migrate.")
        return

    # Create target directories
    envs = ["production", "dry_run", "test", "canary", "unknown", "legacy"]
    for env in envs:
        os.makedirs(f"{NEW_BASE_DIR}/{env}", exist_ok=True)

    # Strategy: 
    # Since we lack metadata to split the legacy DB, we move it to 'legacy' (or 'unknown')
    # and leave Production empty (or copy legacy to production if we assume previous runs were prod?)
    # The prompt says: "If metadata unavailable: mark records environment='unknown' and exclude from optimizer."
    # So we move it to 'unknown' or 'legacy'.
    
    target_path = f"{NEW_BASE_DIR}/legacy/enrichment_metrics.db"
    
    try:
        shutil.move(LEGACY_DB_PATH, target_path)
        logger.info(f"Successfully migrated legacy DB to {target_path}")
        
        # We also need to ensure Production DB exists or will be created?
        # The app creates it on start.
        
    except Exception as e:
        logger.error(f"Migration failed: {e}")

if __name__ == "__main__":
    migrate()
