"""Tests for Frontend Schema Contract."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from news_collector.contracts.frontend_schema import (
    AstroPost,
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
