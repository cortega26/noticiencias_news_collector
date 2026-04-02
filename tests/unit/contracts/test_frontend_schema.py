"""Tests for Frontend Schema Contract."""

from datetime import datetime, timezone

from news_collector.contracts.frontend_schema import (
    AstroPost,
    ImageObject,
    SourceItem,
)


def test_frontend_schema_instantiation():
    """Test instantiating AstroPost pushes coverage."""
    post = AstroPost(
        title="Valid Title for Post",
        excerpt="This is a valid excerpt with more than 10 chars.",
        date=datetime.now(timezone.utc),
        image=ImageObject(src="a.jpg", width=10, height=10, alt="Valid alt text"),
        sources=[SourceItem(title="Src", url="http://example.com")],
    )
    assert post.schema_version >= 1
    assert post.author == "Noticiencias"
