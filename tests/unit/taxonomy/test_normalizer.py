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
                "ciencia": "ciencia",
                "covid19": "covid-19",
            },
            "whitelist_short": ["ia"],
            "max_tags_per_article": 5,
        }

        ortho_config = {
            "corrections": {
                "salud publica": "salud pública",
                "energia oscura": "energía oscura",
                "identidad": "identidad",
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

    def test_charset_repair_matches_frontend_contract(self):
        """Characters the frontend check:tags gate rejects are neutralized."""
        tags = ["ads/cft", "h²maf", "mit sa+p", "c++"]
        result = self.normalizer.sanitize_tags(tags)
        self.assertEqual(result.tags, ["ads cft", "h maf", "mit sa p"])
        self.assertIn({"from": "ads/cft", "to": "ads cft"}, result.replaced)
        self.assertIn("c", result.removed)  # "c++" collapses to a short tag
        self.assertTrue(self.normalizer.validate_tags(result.tags).is_valid)

    def test_charset_repair_is_idempotent(self):
        once = self.normalizer.sanitize_tags(["ads/cft", "mit sa+p"])
        twice = self.normalizer.sanitize_tags(once.tags)
        self.assertEqual(once.tags, twice.tags)
        self.assertEqual(twice.replaced, [])

    def test_charset_repair_applies_after_alias_substitution(self):
        """Canonical maps can reintroduce forbidden chars (covid19 -> covid-19)."""
        result = self.normalizer.sanitize_tags(["covid19"])
        self.assertEqual(result.tags, ["covid 19"])
        self.assertTrue(self.normalizer.validate_tags(result.tags).is_valid)
        self.assertIn({"from": "covid-19", "to": "covid 19"}, result.replaced)

    def test_accents_survive_charset_repair(self):
        result = self.normalizer.sanitize_tags(["energía oscura/gravedad"])
        self.assertEqual(result.tags, ["energía oscura gravedad"])
        self.assertTrue(self.normalizer.validate_tags(result.tags).is_valid)

    def test_missing_config_files_load_as_empty(self):
        normalizer = TagNormalizer(str(Path(self.test_dir.name) / "missing.yml"))
        result = normalizer.sanitize_tags(["Valid Tag"])
        self.assertEqual(result.tags, ["valid tag"])

    def test_non_string_and_punctuation_only_tags(self):
        result = self.normalizer.sanitize_tags([1234, "..."])
        self.assertEqual(result.tags, ["1234"])
        self.assertIn("...", result.removed)

    def test_max_tags_truncation(self):
        result = self.normalizer.sanitize_tags(
            ["uno", "dos", "tres", "cuatro", "cinco", "seis"]
        )
        self.assertEqual(result.tags, ["uno", "dos", "tres", "cuatro", "cinco"])
        self.assertTrue(any("truncated" in warning for warning in result.warnings))

    def test_dedupe_merges_accent_variants(self):
        result = self.normalizer.sanitize_tags(["accion", "acción"])
        self.assertEqual(result.tags, ["accion"])
        self.assertEqual(result.merged, [{"kept": "accion", "dropped": "acción"}])

    def test_self_mapped_orthography_and_alias_are_noops(self):
        result = self.normalizer.sanitize_tags(["identidad", "ciencia"])
        self.assertEqual(result.tags, ["identidad", "ciencia"])
        self.assertEqual(result.replaced, [])

    def test_validate_tags_direct_contract_errors(self):
        long_tag = "a" * 41
        result = self.normalizer.validate_tags(
            ["bad/tag", "other", "ab", long_tag, "uno", "dos"]
        )
        self.assertFalse(result.is_valid)
        self.assertTrue(result.needs_review)
        self.assertEqual(len(result.warnings), 1)
        messages = " ".join(result.errors)
        self.assertIn("Invalid characters", messages)
        self.assertIn("Forbidden stop tag", messages)
        self.assertIn("Tag too short", messages)
        self.assertIn("Tag too long", messages)


if __name__ == "__main__":
    unittest.main()
