"""Plan 036 Step 1: validated scoring workload bounds on ScoringConfig."""

import pytest
from pydantic import ValidationError

from noticiencias.config_schema import ScoringConfig


class TestDefaults:
    def test_defaults_are_applied(self):
        cfg = ScoringConfig()
        assert cfg.page_size == 200
        assert cfg.max_prompt_items == 20
        assert cfg.max_prompt_chars == 16000
        assert cfg.cycle_item_budget is None
        assert cfg.workers == 4

    def test_defaults_round_trip_through_model_dump(self):
        dumped = ScoringConfig().model_dump(mode="python")
        assert dumped["page_size"] == 200
        assert dumped["max_prompt_items"] == 20
        assert dumped["max_prompt_chars"] == 16000
        assert dumped["cycle_item_budget"] is None


class TestRejectsZeroOrNegative:
    @pytest.mark.parametrize(
        "field", ["page_size", "max_prompt_items", "max_prompt_chars", "workers"]
    )
    @pytest.mark.parametrize("bad_value", [0, -1])
    def test_rejects_zero_and_negative(self, field, bad_value):
        with pytest.raises(ValidationError):
            ScoringConfig(**{field: bad_value})

    def test_cycle_item_budget_rejects_zero_and_negative(self):
        with pytest.raises(ValidationError):
            ScoringConfig(cycle_item_budget=0)
        with pytest.raises(ValidationError):
            ScoringConfig(cycle_item_budget=-5)


class TestRejectsExcessive:
    def test_page_size_rejects_over_bound(self):
        with pytest.raises(ValidationError):
            ScoringConfig(page_size=5001)

    def test_max_prompt_items_rejects_over_bound(self):
        with pytest.raises(ValidationError):
            ScoringConfig(max_prompt_items=201)

    def test_max_prompt_chars_rejects_over_and_under_bound(self):
        with pytest.raises(ValidationError):
            ScoringConfig(max_prompt_chars=200001)
        with pytest.raises(ValidationError):
            ScoringConfig(max_prompt_chars=999)

    def test_workers_rejects_over_bound(self):
        with pytest.raises(ValidationError):
            ScoringConfig(workers=65)

    def test_cycle_item_budget_rejects_over_bound(self):
        with pytest.raises(ValidationError):
            ScoringConfig(cycle_item_budget=1_000_001)


class TestAcceptsBoundaryValues:
    def test_boundary_values_are_valid(self):
        cfg = ScoringConfig(
            page_size=5000,
            max_prompt_items=200,
            max_prompt_chars=200000,
            workers=64,
            cycle_item_budget=1_000_000,
        )
        assert cfg.page_size == 5000
        assert cfg.max_prompt_items == 200
        assert cfg.max_prompt_chars == 200000
        assert cfg.workers == 64
        assert cfg.cycle_item_budget == 1_000_000
