from news_collector.scoring.heuristic_scorer import HeuristicScorer
from news_collector.storage.models import Article
from news_collector.scoring.cognitive_scorer import CognitiveScorer
import logging

logging.basicConfig(level=logging.ERROR)

def test_heuristic():
    scorer = HeuristicScorer()

    # Test 1: High Relevance (LatAm) + High Substance (Numbers)
    art1 = Article(
        title="Estudio de la UNAM revela datos sobre el litio en México",
        summary="Científicos de la Universidad Nacional Autónoma de México (UNAM) encontraron que el 50% de las reservas...",
        content="En experimentos con n=1000, p<0.05, el rendimiento aumentó 20% en 2024."
    )
    s1 = scorer.calculate_score(art1)
    print(f"Article 1 (LatAm+Data): {s1}")

    # Test 2: Low Relevance (Ohio) + Low Substance (Opinion)
    art2 = Article(
        title="My opinion on gadgets in Ohio",
        summary="I think gadgets are cool. Here is why.",
        content="Just some random thoughts."
    )
    s2 = scorer.calculate_score(art2)
    print(f"Article 2 (Opinion): {s2}")

    assert s1 > s2
    print("Heuristic Scorer Test PASS")

if __name__ == "__main__":
    test_heuristic()
