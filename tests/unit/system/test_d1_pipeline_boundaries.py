"""Boundary-shape tests for the D1 pipeline seams (plan 135).

Choice: **Option A — real boundary assertions.**  The three scenarios and
the ``test-boundaries`` target are kept, but they are driven by real
collaborators where the boundary is the subject: a real SQLite
``DatabaseManager`` in ``tmp_path``, real ORM rows, and the real contract
models.  Only the LLM/network edge (the scorer) is doubled.  The assertions
are about the payload *shape* crossing each boundary — never about calls made
to a mock:

* export: the returned document validates as ``ExportContractV2`` and its
  article count ids mirror the rows actually inserted;
* validation: the adapter produces ``ArticleValidationPayload`` /
  ``ArticleValidationItem`` and the coordinator persists the documented
  per-item outcome (LAW-B6) for a deliberately short article instead of
  crashing;
* scoring: the scorer only accepts ``ScoringInputModel``-shaped payloads and
  receives articles in the deterministic ``(collected_date, id)`` keyset
  order returned by the real page queries (LAW-B10).

Option A was chosen over the Option B demotion because every seam is already
injectable (``ValidationCoordinator`` / ``ScoringCoordinator`` take their
collaborators explicitly and ``export_latest_articles`` only needs
``db_manager`` + ``logger``), so no change under ``news_collector/system/``
was required to make the gate honest.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from pydantic import ValidationError

from news_collector.contracts.adapters import (
    adapt_to_scoring_input,
    adapt_to_validation_payload,
)
from news_collector.contracts.export import ExportArticleModel, ExportContractV2
from news_collector.contracts.scoring import ScoringInputModel
from news_collector.contracts.validation import (
    ArticleValidationItem,
    ArticleValidationPayload,
)
from news_collector.storage.database import DatabaseManager
from news_collector.storage.models import Article
from news_collector.system import NewsCollectorSystem
from news_collector.validation.validator import ContentValidator

_NOW = datetime.now(timezone.utc)


class _NullLogger:
    """No-op logging facade — logging is an edge, not the subject under test."""

    def create_module_logger(self, name: str) -> "_NullLogger":
        return self

    def debug(self, *args: Any, **kwargs: Any) -> None:
        pass

    def info(self, *args: Any, **kwargs: Any) -> None:
        pass

    def warning(self, *args: Any, **kwargs: Any) -> None:
        pass

    def error(self, *args: Any, **kwargs: Any) -> None:
        pass

    def log_error_with_context(self, *args: Any, **kwargs: Any) -> None:
        pass


class RecordingScorer:
    """LLM-edge double that enforces the typed scoring boundary.

    It is not a ``MagicMock``: it validates every payload against the real
    contract (so a raw-dict boundary fails loudly) and records the order in
    which the coordinator handed articles to it.
    """

    def __init__(self) -> None:
        self.batches: list[list[dict[str, Any]]] = []

    async def score_batch_async(
        self, payloads: list[dict[str, Any]], **kwargs: Any
    ) -> list[dict[str, Any]]:
        for payload in payloads:
            ScoringInputModel.model_validate(payload)
        self.batches.append(list(payloads))
        return [
            {
                "final_score": 0.75,
                "should_include": True,
                "components": {
                    "source_credibility": 0.9,
                    "recency": 0.8,
                    "content_quality": 0.7,
                    "engagement": 0.5,
                },
                "weights": {},
                "version": "test",
            }
            for _ in payloads
        ]

    @property
    def article_ids(self) -> list[list[int]]:
        return [
            [ScoringInputModel.model_validate(payload).article.id for payload in batch]
            for batch in self.batches
        ]


@pytest.fixture()
def db_manager(tmp_path) -> DatabaseManager:
    """A real SQLite database — no ORM objects are faked at this boundary."""
    manager = DatabaseManager({"type": "sqlite", "path": tmp_path / "boundaries.db"})
    try:
        yield manager
    finally:
        manager.close()


def _system(
    db_manager: DatabaseManager,
    *,
    validator: Any = None,
    scorer: Any = None,
) -> NewsCollectorSystem:
    system = NewsCollectorSystem()
    system.is_initialized = True
    system.db_manager = db_manager
    system.validator = validator
    system.scorer = scorer
    system.logger = _NullLogger()
    return system


def _article(
    article_id: int,
    *,
    title: str,
    content: str = "content",
    source_id: str = "source-a",
    source_name: str = "Source A",
    status: str = "pending",
    final_score: float | None = None,
    collected_at: datetime | None = None,
    published_at: datetime | None = None,
    metadata: dict[str, Any] | None = None,
) -> Article:
    return Article(
        id=article_id,
        title=title,
        url=f"https://example.com/articles/{article_id}",
        summary=f"Summary for {title}",
        content=content,
        source_id=source_id,
        source_name=source_name,
        processing_status=status,
        final_score=final_score,
        collected_date=collected_at or _NOW,
        published_date=published_at,
        article_metadata=metadata or {},
        content_mode="full_text",
        word_count=120,
    )


def _insert(db_manager: DatabaseManager, articles: list[Article]) -> None:
    with db_manager.get_session() as session:
        session.add_all(articles)


def test_export_boundary_uses_contract(
    db_manager: DatabaseManager,
) -> None:
    """The export document is an ``ExportContractV2`` built from real rows."""
    articles = [
        _article(
            1,
            title="Article one",
            source_id="source-a",
            source_name="Source A",
            status="completed",
            final_score=0.9,
            metadata={"enrichment": {"topics": ["space"]}},
        ),
        _article(
            2,
            title="Article two",
            source_id="source-b",
            source_name="Source B",
            status="completed",
            final_score=0.8,
        ),
        _article(
            3,
            title="Article three",
            source_id="source-c",
            source_name="Source C",
            status="completed",
            final_score=0.7,
        ),
    ]
    _insert(db_manager, articles)

    payload = _system(db_manager).export_latest_articles(limit=3)

    # Shape: the public dict round-trips through the sealed export contract.
    contract = ExportContractV2.model_validate(payload)
    assert isinstance(contract.articles[0], ExportArticleModel)

    # Content: the contract reflects the rows actually persisted, not a fake.
    assert contract.contract == "news_collector.export.v2"
    assert contract.version == "2.0"
    assert contract.article_count == len(articles) == 3
    assert [article.id for article in contract.articles] == [1, 2, 3]
    assert [article.score for article in contract.articles] == [0.9, 0.8, 0.7]
    assert contract.articles[0].metadata["enrichment"]["topics"] == ["space"]
    assert isinstance(payload["exported_at"], str) and payload["exported_at"]


def test_validation_boundary_uses_payload(
    db_manager: DatabaseManager,
) -> None:
    """Validation crosses the boundary as a typed payload, item by item."""
    valid_content = "mars rover riverbed " * 30
    _insert(
        db_manager,
        [
            _article(
                1,
                title="Mars rover finds ancient riverbed",
                content=valid_content,
                collected_at=_NOW - timedelta(minutes=2),
            ),
            _article(
                2,
                title="Stub article",
                content="too short",
                collected_at=_NOW - timedelta(minutes=1),
            ),
        ],
    )

    system = _system(db_manager, validator=ContentValidator())

    # Adapter boundary: real ORM rows become the typed, sealed payload.
    rows = db_manager.get_pending_articles(limit=100)
    payload = adapt_to_validation_payload(rows)
    assert isinstance(payload, ArticleValidationPayload)
    assert all(isinstance(item, ArticleValidationItem) for item in payload.articles)
    assert [item.id for item in payload.articles] == [1, 2]
    assert payload.articles[1].content == "too short"

    result = system._execute_validation({}, dry_run=False)

    # Outcome boundary (LAW-B6): the short item is rejected per-item, not
    # raised as a crash; the valid item is accepted.
    assert result["success"] is True
    assert result["validated_count"] == 2
    assert result["rejected_count"] == 1
    assert result["details"]["invalid"][0]["rule"] == "min_content_length"

    invalid_item = result["details"]["invalid"][0]["article"]
    assert set(invalid_item) == set(ArticleValidationItem.model_fields)
    assert ArticleValidationItem.model_validate(invalid_item).id == 2

    # The per-item outcome is persisted: rejected vs validated statuses.
    with db_manager.get_session() as session:
        statuses = {
            article.id: article.processing_status
            for article in session.query(Article).order_by(Article.id)
        }
    assert statuses == {1: "validated", 2: "rejected"}

    # Sealed boundary: a raw ORM dump (extra keys) is not accepted as an item.
    with pytest.raises(ValidationError):
        ArticleValidationItem.model_validate({**invalid_item, "final_score": 0.9})


@pytest.mark.asyncio
async def test_scoring_boundary_uses_input_model(
    db_manager: DatabaseManager,
) -> None:
    """Scoring sees typed payloads in deterministic keyset order."""
    _insert(
        db_manager,
        [
            _article(
                1,
                title="Pending one",
                source_id="source-a",
                status="validated",
                collected_at=_NOW - timedelta(minutes=3),
            ),
            _article(
                2,
                title="Pending three",
                source_id="source-a",
                status="validated",
                collected_at=_NOW - timedelta(minutes=1),
            ),
            _article(
                3,
                title="Pending two",
                source_id="source-b",
                status="validated",
                collected_at=_NOW - timedelta(minutes=2),
            ),
            _article(
                4,
                title="Completed rescore",
                source_id="source-b",
                status="completed",
                final_score=0.4,
                collected_at=_NOW - timedelta(minutes=4),
            ),
        ],
    )

    # Deterministic ordering (LAW-B10) comes from the real page queries, not
    # from the order rows were inserted: (collected_date, id) ascending.
    first_page = db_manager.get_pending_articles_page(limit=2, status="validated")
    assert [article.id for article in first_page.items] == [1, 3]
    assert first_page.next_cursor is not None
    second_page = db_manager.get_pending_articles_page(
        limit=2, status="validated", cursor=first_page.next_cursor
    )
    assert [article.id for article in second_page.items] == [2]
    assert second_page.next_cursor is None

    rescore_page = db_manager.get_completed_articles_for_rescoring_page(limit=10)
    assert [article.id for article in rescore_page.items] == [4]

    rows = db_manager.get_pending_articles(limit=100, status="validated")
    model = adapt_to_scoring_input(rows[0], {"name": "Source A"})
    assert isinstance(model, ScoringInputModel)
    assert model.article.id == 1
    assert model.source_config == {"name": "Source A"}

    # A raw flat ORM dump is not a valid scored payload — the typed wrapper is
    # part of the boundary, not an implementation detail.
    with pytest.raises(ValidationError):
        ScoringInputModel.model_validate(rows[0].to_dict())

    scorer = RecordingScorer()
    result = await _system(db_manager, scorer=scorer)._execute_scoring(
        {}, dry_run=False
    )

    assert result["success"] is True
    assert result["statistics"]["new_articles_scored"] == 3
    assert result["statistics"]["completed_articles_rescored"] == 1
    assert result["pages_processed"] == 2
    assert scorer.article_ids == [[1, 3, 2], [4]]

    # Every payload handed to the scorer is the typed dump shape.
    for batch in scorer.batches:
        for payload in batch:
            assert set(payload) == {"article", "source_config"}
            assert payload["article"]["source_id"] in {"source-a", "source-b"}

    # The scores were persisted against the real rows.
    persisted = {
        article.id: article for article in db_manager.get_articles_by_score(10)
    }
    assert set(persisted) == {1, 2, 3, 4}
    assert all(article.final_score == 0.75 for article in persisted.values())
    assert persisted[1].score_components["source_credibility"] == 0.9
