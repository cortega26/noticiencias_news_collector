import unittest
from pathlib import Path
import tempfile
import yaml
from news_collector.taxonomy.normalizer import TagNormalizer

class TestTagNormalizer(unittest.TestCase):

    def setUp(self):
        # Create a temporary config file
        self.test_dir = tempfile.TemporaryDirectory()
        self.config_path = Path(self.test_dir.name) / "test_tags.yml"
        
        config = {
            "stop_tags": ["other", "varios", "misc"],
            "alias_map": {
                "ia": "inteligencia artificial",
                "ai": "inteligencia artificial",
                "salud publica": "salud pública",
                "energia oscura": "energía oscura"
            },
            "whitelist_short": ["ia"],
            "max_tags_per_article": 5
        }
        
        with open(self.config_path, "w") as f:
            yaml.dump(config, f)
            
        self.normalizer = TagNormalizer(str(self.config_path))

    def tearDown(self):
        self.test_dir.cleanup()

    def test_basic_normalization(self):
        tags = ["  Salud   Pública ", "Ciencia-Ficción", "UPPERCASE"]
        result = self.normalizer.normalize_tags(tags)
        self.assertEqual(result.tags, ["ciencia ficción", "salud pública", "uppercase"])

    def test_stop_tags(self):
        tags = ["science", "other", "varios", "valid"]
        result = self.normalizer.normalize_tags(tags)
        self.assertEqual(result.tags, ["science", "valid"])
        self.assertIn("other", result.removed)

    def test_short_long_tags(self):
        # "s" is too short, "ia" is whitelisted short
        # "very long tag..." > 40 chars
        long_tag = "a" * 41
        tags = ["s", "ia", long_tag, "ok", "sol"] # "sol" is 3 chars, should be kept. "ok" is 2 chars, removed.
        result = self.normalizer.normalize_tags(tags)
        self.assertEqual(result.tags, ["inteligencia artificial", "sol"]) 
        self.assertIn("s", result.removed)
        self.assertIn("ok", result.removed)
        self.assertIn(long_tag, result.removed)

    def test_alias_mapping(self):
        tags = ["ia", "ai", "artificial intelligence"] # "artificial intelligence" not in map but let's add one more
        # Wait, my setup has 'ia', 'ai'.
        tags = ["ia", "ai"]
        result = self.normalizer.normalize_tags(tags)
        # Both map to "inteligencia artificial", and should dedupe to one
        self.assertEqual(result.tags, ["inteligencia artificial"])
        self.assertTrue(len(result.replaced) >= 1)

    def test_deduplication(self):
        # "energía oscura", "energia oscura", "energia-oscura"
        # All normalize to "energia oscura" (stripped accents) or "energía oscura" depending on rules
        # My implementation:
        # dedupe_key: basic_norm -> strip_accents
        # basic_norm("energía oscura") -> "energía oscura"
        # strip_accents("energía oscura") -> "energia oscura"
        # So all have key "energia oscura"
        
        tags = ["energía oscura", "energia oscura", "energia-oscura"]
        result = self.normalizer.normalize_tags(tags)
        
        # It should pick the best one.
        # "energía oscura" (len 14)
        # "energia oscura" (len 14)
        # "energia-oscura" -> norm "energia oscura" (len 14) (hyphen replaced by space in basic_norm)
        
        # Stability check: it preserves the first one seen if lengths equal?
        # My code:
        # if len(t) < len(existing): replace
        # else: keep existing
        
        # Normalized inputs to dedupe step:
        # "energía oscura", "energia oscura", "energia oscura"
        
        # 1. "energía oscura". key="energia oscura". map={"energia oscura": "energía oscura"}
        # 2. "energia oscura". key="energia oscura". len("energia oscura")=14. len("energía oscura")=14. 
        #    14 < 14 False. Keep existing "energía oscura".
        # 3. "energia oscura". key="energia oscura". Keep existing.
        
        self.assertEqual(result.tags, ["energía oscura"])
        
    def test_deduplication_length_preference(self):
        # "shorter" vs "longer version" (keys must match... wait, keys match only if accents/spaces differ)
        # If I have "foo" and "foo bar", keys are different.
        # This dedupe is for NEAR duplicates (accents, punctuation).
        
        # Case: "cancion" vs "canción"
        tags = ["cancion", "canción"]
        result = self.normalizer.normalize_tags(tags)
        # "canción" (7) vs "cancion" (7). Prefers first seen?
        self.assertEqual(result.tags, ["cancion"])
        
        tags2 = ["canción", "cancion"]
        result2 = self.normalizer.normalize_tags(tags2)
        self.assertEqual(result2.tags, ["canción"])

    def test_max_tags(self):
        tags = [f"tag{i}" for i in range(10)]
        result = self.normalizer.normalize_tags(tags)
        self.assertEqual(len(result.tags), 5)
        self.assertTrue(len(result.warnings) > 0)

    def test_idempotency(self):
        tags = ["  Salud   Pública ", "energia-oscura", "other", "ia"]
        result1 = self.normalizer.normalize_tags(tags)
        result2 = self.normalizer.normalize_tags(result1.tags)
        self.assertEqual(result1.tags, result2.tags)

if __name__ == "__main__":
    unittest.main()
