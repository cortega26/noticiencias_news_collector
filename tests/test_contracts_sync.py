from datetime import date

import pytest
import yaml
from news_collector.contracts.frontend_schema import AstroPost, HeadlinesVariants


def test_astro_post_serialization():
    """Verify that AstroPost serializes to valid YAML matching Frontend contract."""

    post = AstroPost(
        title="Test Title",
        excerpt="This is a test excerpt that is long enough.",
        date=date(2023, 1, 1),
        categories=["Ciencia"],
        tags=["tag1", "tag2"],
        image="http://example.com/image.jpg",
        source_url="http://source.com",
        refinery_id="123456",
        headlines_variants=HeadlinesVariants(question="Q?", benefit="B"),
    )

    model_dict = post.model_dump(exclude_none=True)
    yaml_output = yaml.dump(model_dict, sort_keys=False)

    # Assertions
    assert "title: Test Title" in yaml_output
    assert "schema_version: 1" in yaml_output  # Default
    assert (
        "refinery_id: '123456'" in yaml_output
        or 'refinery_id: "123456"' in yaml_output
        or "refinery_id: 123456" in yaml_output
    )

    # Verify strict validation
    with pytest.raises(ValueError):
        AstroPost(title="Short", excerpt="Short", date=date(2023, 1, 1))  # Too short


if __name__ == "__main__":
    # fast manual run
    try:
        test_astro_post_serialization()
        print("✅ AstroPost Serialization Test Passed")
    except Exception as e:
        print(f"❌ AstroPost Serialization Test Failed: {e}")
        exit(1)
