import tempfile
import unittest
from pathlib import Path

import yaml
from news_collector.taxonomy.normalizer import TagNormalizer


class TestTagNormalizer(unittest.TestCase):

    def setUp(self):
        # Create a temporary config environment
        self.test_dir = tempfile.TemporaryDirectory()
        self.config_path = Path(self.test_dir.name) / "test_tags.yml"
        self.ortho_path = Path(self.test_dir.name) / "orthography.yml"

        config = {
            "stop_tags": ["other", "varios", "misc"],
            "alias_map": {
                "ia": "inteligencia artificial",
                "ai": "inteligencia artificial",
            },
            "whitelist_short": ["ia"],
            "max_tags_per_article": 5,
        }

        ortho_config = {
            "corrections": {
                "salud publica": "salud pública",
                "energia oscura": "energía oscura",
            }
        }

        with open(self.config_path, "w") as f:
            yaml.dump(config, f)

        with open(self.ortho_path, "w") as f:
            yaml.dump(ortho_config, f)

        self.normalizer = TagNormalizer(str(self.config_path))

    def tearDown(self):
        self.test_dir.cleanup()

    def test_basic_normalization(self):
        tags = ["  Salud   Pública ", "Ciencia-Ficción", "UPPERCASE"]
        # ortho should apply: 'salud publica' -> 'salud pública'
        # 'ciencia-ficcion' -> basic 'ciencia ficcion'. No ortho.
        result = self.normalizer.sanitize_tags(tags)
        # Note: Order is preserved in sanitize_tags
        self.assertEqual(result.tags, ["salud pública", "ciencia ficción", "uppercase"])

    def test_orthography_correction(self):
        tags = ["energia oscura", "energia-oscura"]
        # Both normalize to 'energia oscura' via basic norm.
        # Ortho maps 'energia oscura' -> 'energía oscura'.
        result = self.normalizer.sanitize_tags(tags)
        self.assertEqual(result.tags, ["energía oscura"])

    def test_semantic_alias(self):
        tags = ["ia", "ai"]
        result = self.normalizer.sanitize_tags(tags)
        self.assertEqual(result.tags, ["inteligencia artificial"])

    def test_stop_tags(self):
        tags = ["science", "other", "varios", "valid"]
        result = self.normalizer.sanitize_tags(tags)
        self.assertEqual(result.tags, ["science", "valid"])
        self.assertIn("other", result.removed)

    def test_short_long_tags(self):
        long_tag = "a" * 41
        # 'sol' is 3 chars, kept. 'ok' is 2 chars, removed (not in whitelist).
        tags = ["s", "ia", long_tag, "ok", "sol"]
        result = self.normalizer.sanitize_tags(tags)
        # 'ia' -> 'inteligencia artificial' via alias
        self.assertIn("inteligencia artificial", result.tags)
        self.assertIn("sol", result.tags)
        self.assertIn("s", result.removed)
        self.assertIn("ok", result.removed)
        self.assertIn(long_tag, result.removed)

    def test_deduplication(self):
        tags = ["energía oscura", "energia oscura"]
        # Both become 'energía oscura' via ortho.
        result = self.normalizer.sanitize_tags(tags)
        self.assertEqual(result.tags, ["energía oscura"])

    def test_idempotency(self):
        tags = ["  Salud   Pública ", "energia-oscura", "other", "ia"]
        result1 = self.normalizer.sanitize_tags(tags)
        result2 = self.normalizer.sanitize_tags(result1.tags)
        self.assertEqual(result1.tags, result2.tags)

    def test_period_stripping(self):
        """Periods from abbreviations (e.g. 'vera c. rubin') are stripped."""
        tags = ["observatorio vera c. rubin"]
        result = self.normalizer.sanitize_tags(tags)
        self.assertEqual(result.tags, ["observatorio vera c rubin"])
        val_result = self.normalizer.validate_tags(result.tags)
        self.assertTrue(val_result.is_valid)

    def test_period_stripping_no_period(self):
        """Tags without periods are unchanged by period stripping."""
        tags = ["agujeros negros", "materia oscura", "ia"]
        result = self.normalizer.sanitize_tags(tags)
        expected = ["agujeros negros", "materia oscura", "inteligencia artificial"]
        self.assertEqual(result.tags, expected)


if __name__ == "__main__":
    unittest.main()
