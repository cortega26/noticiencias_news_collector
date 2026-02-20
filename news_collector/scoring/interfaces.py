"""
Module role: Defines the protocol and interface abstractions for asynchronous article scorers.

Inputs:
- Dictionaries containing raw or parsed article configurations (`article_data`).

Outputs:
- Dictionaries containing computed scoring results, including final scores, metrics, and reasoning.

Side effects:
- None.

Invariants:
- Scoring systems must implement the `score_article_async` method.
- Interface allows type-checking and runtime verification via `@runtime_checkable`.

Failure modes:
- Implementation specific; the interface itself guarantees no specific failure modes beyond signature enforcement.
"""
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
