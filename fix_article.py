
import sys
import logging
from pathlib import Path

# Add project root to sys.path
project_root = Path(__file__).resolve().parent
sys.path.insert(0, str(project_root))

from news_collector.system import create_system
from news_collector.utils.full_text import fetch_full_article
from news_collector.storage.models import Article

# Setup basic logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ManualRepair")

def repair_article(url):
    logger.info(f"🔧 Starting repair for: {url}")
    
    # 1. Fetch Content
    logger.info("🌍 Fetching full text directly...")
    content = fetch_full_article(url)
    
    if not content or len(content) < 1000:
        logger.error(f"❌ Failed to fetch valid content (Length: {len(content) if content else 0})")
        return False
        
    logger.info(f"✅ Fetched content successfully: {len(content)} chars")
    
    # 2. Update Database
    system = create_system()
    if not system.initialize():
        logger.error("❌ System initialization failed.")
        return False
    db = system.db_manager
    
    with db.get_session() as session:
        article = session.query(Article).filter(Article.url.like(f"%{url}%")).first()
        
        if not article:
            # Try searching by original_url in metadata if needed, but LIKE should catch it
            # The URL provided might be slighty different from stored (http vs https, trailing slash)
            # So let's try strict first
            article = session.query(Article).filter_by(url=url).first()
            
        if not article:
            logger.error("❌ Article not found in database. Cannot repair.")
            return False
            
        logger.info(f"📝 Updating Article ID {article.id} (Current length: {len(article.content) if article.content else 0})")
        
        article.content = content
        article.summary = content[:500] + "..." # Ensure summary is populated if missing
        
        session.add(article)
        # Session commits on exit of context manager
        
    logger.info("💾 Database updated successfully.")
    return True

if __name__ == "__main__":
    target_url = "https://livescience.com/animals/cats/ancient-mummified-cheetahs-discovered-in-saudi-arabia-contain-preserved-dna-from-the-long-lost-population"
    if len(sys.argv) > 1:
        target_url = sys.argv[1]
        
    success = repair_article(target_url)
    if success:
        print("\n🎉 REPAIR COMPLETE. You can now use the Refinery.")
    else:
        print("\n💥 REPAIR FAILED.")
