import unittest
from datetime import datetime

from news_collector.contracts.scoring import ScoringComponentsModel, ScoringRequestModel
from pydantic import ValidationError


class TestScoringContracts(unittest.TestCase):

    def test_components_valid(self):
        comp = ScoringComponentsModel(
            source_credibility=0.8, recency=1.0, content_quality=0.5, engagement=0.1
        )
        self.assertEqual(comp.get_engagement_value(), 0.1)

    def test_components_invalid_range(self):
        with self.assertRaises(ValidationError) as cm:
            ScoringComponentsModel(
                source_credibility=1.5, recency=1.0, content_quality=0.5, engagement=0.1
            )
        self.assertIn("must be between 0 and 1", str(cm.exception))

    def test_components_missing_engagement(self):
        with self.assertRaises(ValidationError) as cm:
            ScoringComponentsModel(
                source_credibility=0.5, recency=0.5, content_quality=0.5
            )
        self.assertIn("must define either 'engagement'", str(cm.exception))

    def test_components_engagement_potential(self):
        comp = ScoringComponentsModel(
            source_credibility=0.5,
            recency=0.5,
            content_quality=0.5,
            engagement_potential=0.7,
        )
        self.assertEqual(comp.get_engagement_value(), 0.7)

    def test_request_valid(self):
        comp = ScoringComponentsModel(
            source_credibility=1.0, recency=1.0, content_quality=1.0, engagement=1.0
        )
        req = ScoringRequestModel(
            final_score=0.9,
            should_include=True,
            components=comp,
            weights={"w1": 0.5, "w2": 0.5},
            calculated_at=datetime.now(),
        )
        data = req.model_dump_for_storage()
        self.assertEqual(data["final_score"], 0.9)

    def test_request_bad_score(self):
        comp = ScoringComponentsModel(
            source_credibility=1.0, recency=1.0, content_quality=1.0, engagement=1.0
        )
        with self.assertRaises(ValidationError) as cm:
            ScoringRequestModel(final_score=1.1, should_include=True, components=comp)
        self.assertIn("final_score must be between 0 and 1", str(cm.exception))

    def test_request_bad_weights(self):
        comp = ScoringComponentsModel(
            source_credibility=1.0, recency=1.0, content_quality=1.0, engagement=1.0
        )
        with self.assertRaises(ValidationError) as cm:
            ScoringRequestModel(
                final_score=0.5,
                should_include=True,
                components=comp,
                weights={"w1": 0.5},  # Sum != 1.0
            )
        self.assertIn("weights must sum to approximately 1.0", str(cm.exception))

    def test_request_bad_weight_value(self):
        comp = ScoringComponentsModel(
            source_credibility=1.0, recency=1.0, content_quality=1.0, engagement=1.0
        )
        with self.assertRaises(ValidationError) as cm:
            ScoringRequestModel(
                final_score=0.5,
                should_include=True,
                components=comp,
                weights={"w1": 1.5, "w2": -0.5},  # Sums to 1.0 but invalid values
            )
        self.assertIn("between 0 and 1", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
