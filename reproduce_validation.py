from news_collector import get_database_manager
from news_collector.storage.models import Article
from news_collector.validation.validator import ContentValidator

def reproduce():
    db = get_database_manager()
    validator = ContentValidator()
    
    with db.get_session() as session:
        article = session.query(Article).filter_by(id=8).first()
        if not article:
            print("Article 8 not found.")
            return

        # Prepare dict as system.py does
        article_dict = article.to_dict()
        article_dict["content"] = article.content
        
        result = validator.validate_article(article_dict)
        
        print(f"Article ID: {article.id}")
        print(f"Title: {article.title}")
        print(f"Is Valid: {result.is_valid}")
        if not result.is_valid:
            print(f"Reason: {result.reason}")
            print(f"Rule: {result.rule_name}")
        else:
            print("Article passed validation (Unexpected!)")

if __name__ == "__main__":
    reproduce()
