"""Plan 123 step 2: unset/unknown environment tiers fail closed.

The serving auth gates warn-and-serve ONLY on the exact "development" tier
(`is_explicit_development`). Anything else — the "unset" RUNTIME default, an
empty string, or an unknown tier name — must 503 when the API key is missing.
"""

import pytest

from news_collector.config.runtime import RuntimeSettings, is_explicit_development


def test_runtime_default_environment_is_not_development():
    """A process that never loaded config must not fail open."""
    assert RuntimeSettings().environment != "development"
    assert not is_explicit_development(RuntimeSettings().environment)


def test_explicit_development_only():
    assert is_explicit_development("development") is True


@pytest.mark.parametrize(
    "tier", ["unset", "", "prod", "Development", " development ", "production", "staging", "test"]
)
def test_non_development_tiers_fail_closed(tier):
    assert is_explicit_development(tier) is False


@pytest.mark.parametrize("tier", [None, 0, b"development", ["development"]])
def test_non_string_environments_fail_closed(tier):
    assert is_explicit_development(tier) is False
