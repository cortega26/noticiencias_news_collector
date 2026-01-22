from typing import Any, Dict, Protocol, runtime_checkable

@runtime_checkable
class AsyncScorer(Protocol):
    """Protocol for asynchronous article scorers."""

    async def score_article_async(self, article_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Score an article asynchronously.

        Args:
            article_data: Dictionary containing article data (processed from ORM).

        Returns:
            Dictionary containing score data (score, metrics, reasoning).
        """
        ...
