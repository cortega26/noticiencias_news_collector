from news_collector import get_database_manager
from news_collector.storage.models import Article

db = get_database_manager()
with db.get_session() as session:
    article = session.query(Article).filter_by(id=8).first()
    if article:
        print(f"TITLE: {article.title}")
        print(f"URL: {article.url}")
        print("-" * 20)
        print(f"CONTENT START (First 500 chars):\n{article.content[:500] if article.content else 'None'}")
        print("-" * 20)
        print(f"CONTENT END (Last 500 chars):\n{article.content[-500:] if article.content else 'None'}")
    else:
        print("Article 8 not found.")
