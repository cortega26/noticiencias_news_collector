"""Tests for Frontend Schema Contract."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from news_collector.contracts.frontend_schema import (
    AstroPost,
    FactCheckItem,
    GlossaryItem,
    ImageObject,
    SocialConfig,
    SourceItem,
)

_HEX64 = "a" * 64


def _base_post(**overrides):
    data = dict(
        title="Valid Title for Post",
        excerpt="This is a valid excerpt with more than 10 chars.",
        date=datetime.now(timezone.utc),
        image=ImageObject(src="a.jpg", width=10, height=10, alt="Valid alt text"),
        sources=[SourceItem(title="Src", url="http://example.com")],
    )
    data.update(overrides)
    return data


def test_frontend_schema_instantiation():
    """Test instantiating AstroPost pushes coverage."""
    post = AstroPost(**_base_post())
    assert post.schema_version >= 1
    assert post.author == "Noticiencias"


# --------------------------------------------------------------------------- #
# social contract (plan social-distribution §9)
# --------------------------------------------------------------------------- #


def test_social_absent_is_none():
    assert AstroPost(**_base_post()).social is None


@pytest.mark.parametrize(
    "social",
    [
        {},
        {"publish": False},
        {"publish": True, "id": _HEX64},
        {"publish": False, "id": _HEX64},
        {"id": _HEX64},  # publish defaults to False
    ],
)
def test_social_accepted_shapes(social):
    post = AstroPost(**_base_post(social=social))
    assert isinstance(post.social, SocialConfig)


def test_social_publish_defaults_to_false():
    assert AstroPost(**_base_post(social={})).social.publish is False


@pytest.mark.parametrize("bad_publish", ["true", "false", 0, 1, None])
def test_social_publish_rejects_non_bool(bad_publish):
    with pytest.raises(ValidationError):
        AstroPost(**_base_post(social={"publish": bad_publish}))


def test_social_id_required_when_publishing():
    with pytest.raises(ValidationError, match="social.id is required"):
        AstroPost(**_base_post(social={"publish": True}))
    with pytest.raises(ValidationError):
        AstroPost(**_base_post(social={"publish": True, "id": ""}))


@pytest.mark.parametrize(
    "bad_id",
    ["abc", "A" * 64, "g" * 64, _HEX64 + "a", _HEX64[:-1]],
)
def test_social_id_pattern_enforced(bad_id):
    with pytest.raises(ValidationError):
        AstroPost(**_base_post(social={"publish": False, "id": bad_id}))


def test_social_rejects_unknown_keys():
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        AstroPost(**_base_post(social={"publish": True, "id": _HEX64, "channel": "fb"}))


def test_social_explicit_null_rejected():
    with pytest.raises(ValidationError, match="not null"):
        AstroPost(**_base_post(social=None))


def test_astropost_still_ignores_unknown_top_level_extras():
    # The social object is strict, but AstroPost itself keeps ignoring extras.
    post = AstroPost(**_base_post(some_unknown_future_field="whatever"))
    assert not hasattr(post, "some_unknown_future_field")


# --------------------------------------------------------------------------- #
# v2 editorial contract (mirrors schema_version >= 2 superRefine in
# src/content.config.ts)
# --------------------------------------------------------------------------- #


def _base_v2_post(**overrides):
    data = _base_post(
        schema_version=2,
        summary_points=["First point", "Second point"],
        glossary=[GlossaryItem(term="Term", definition="Definition")],
        fact_check=[FactCheckItem(label="Claim", status="verified")],
        confidence="high",
    )
    data.update(overrides)
    return data


def test_v1_without_editorial_fields_still_validates():
    post = AstroPost(**_base_post())
    assert post.schema_version == 1


def test_v2_valid_post_passes():
    post = AstroPost(**_base_v2_post())
    assert post.schema_version == 2


def test_v2_missing_summary_points_raises():
    data = _base_v2_post()
    del data["summary_points"]
    with pytest.raises(ValidationError, match="summary_points is required"):
        AstroPost(**data)


def test_v2_summary_points_too_few_raises():
    with pytest.raises(ValidationError, match="summary_points must have 2-5 items"):
        AstroPost(**_base_v2_post(summary_points=["Only one"]))


def test_v2_summary_points_too_many_raises():
    with pytest.raises(ValidationError, match="summary_points must have 2-5 items"):
        AstroPost(**_base_v2_post(summary_points=["a", "b", "c", "d", "e", "f"]))


def test_v2_missing_glossary_raises():
    data = _base_v2_post()
    del data["glossary"]
    with pytest.raises(ValidationError, match="glossary is required"):
        AstroPost(**data)


def test_v2_missing_fact_check_raises():
    data = _base_v2_post()
    del data["fact_check"]
    with pytest.raises(ValidationError, match="fact_check is required"):
        AstroPost(**data)


def test_v2_missing_confidence_raises():
    data = _base_v2_post()
    del data["confidence"]
    with pytest.raises(ValidationError, match="confidence is required"):
        AstroPost(**data)


def test_v2_missing_sources_raises():
    data = _base_v2_post()
    data["sources"] = []
    with pytest.raises(ValidationError, match="sources is required"):
        AstroPost(**data)


def test_v2_why_it_matters_absent_is_valid():
    # P0-06 / DEC-003: no minimum — absence beats fabrication.
    post = AstroPost(**_base_v2_post())
    assert post.why_it_matters is None
