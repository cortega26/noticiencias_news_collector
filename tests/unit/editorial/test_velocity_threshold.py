"""Test for C-03: Minimum auditor threshold for velocity mode (F-0027).

Velocity mode must enforce a minimum auditor_threshold of 3.0 so that
zero-quality articles are rejected even when editorial speed is prioritized.
"""

import pytest

from news_collector.editorial.policy import EditorialPolicy


class TestVelocityModeMinimumThreshold:
    """C-03 / F-0027: velocity mode sets auditor_threshold >= 3.0."""

    def test_velocity_mode_rejects_below_minimum(self):
        """Articles with epistemic score below 3.0 must be rejected in velocity mode."""
        policy = EditorialPolicy.from_mode("velocity")

        assert policy.auditor_threshold == 3.0
        assert policy.mode == "velocity"

        # Score 2.0 < threshold 3.0 → should be blocked
        score = 2.0
        assert score < policy.auditor_threshold

    def test_velocity_mode_accepts_above_threshold(self):
        """Articles with epistemic score >= 3.0 pass in velocity mode."""
        policy = EditorialPolicy.from_mode("velocity")

        score = 5.0
        assert score >= policy.auditor_threshold

    def test_velocity_threshold_no_longer_zero(self):
        """Regression: velocity mode must NOT have auditor_threshold=0.0."""
        policy = EditorialPolicy.from_mode("velocity")

        assert policy.auditor_threshold > 0.0, (
            "Velocity mode auditor_threshold must not be 0.0 (F-0027)"
        )

    def test_standard_and_strict_unaffected(self):
        """Other modes retain their original thresholds."""
        standard = EditorialPolicy.from_mode("standard")
        strict = EditorialPolicy.from_mode("strict")

        assert standard.auditor_threshold == 8.0
        assert strict.auditor_threshold == 8.5
