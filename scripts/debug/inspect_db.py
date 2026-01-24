from news_collector.storage.database import DatabaseManager
from news_collector.storage.models import Article
from sqlalchemy import func

try:
    db = DatabaseManager()
    with db.get_session() as session:
        # Get count by status
        counts = (
            session.query(Article.processing_status, func.count(Article.id))
            .group_by(Article.processing_status)
            .all()
        )
        print("Status Counts:")
        for status, count in counts:
            print(f"  {status}: {count}")

        # Get recent pending articles
        pending = (
            session.query(Article)
            .filter(Article.processing_status == "pending")
            .order_by(Article.collected_date.desc())
            .limit(5)
            .all()
        )
        print("\nTop 5 Pending Articles:")
        for a in pending:
            print(f"  - [{a.processing_status}] {a.title} (ID: {a.id})")

except Exception as e:
    print(f"Error: {e}")
