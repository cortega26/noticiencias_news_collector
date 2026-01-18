import unittest
from unittest.mock import MagicMock
from news_collector.editorial.council import EditorialCouncil, CouncilResult
from news_collector.utils.llm_client import LLMClient

class TestEditorialCouncil(unittest.TestCase):
    def test_approval_logic(self):
        # Mock LLM Client
        mock_llm = MagicMock(spec=LLMClient)
        
        # Scenario 1: Perfect Article
        mock_response_good = {
          "council_assessments": [
            {"role": "Científico", "score": 4, "observation": "Good"},
            {"role": "Escéptico", "score": 4, "observation": "Good"},
            {"role": "Curioso", "score": 5, "observation": "Great"},
            {"role": "Editor", "score": 5, "observation": "perfect"}
          ],
          "editorial_synthesis": {},
          "editor_approval": "Sí, es Noticiencias"
        }
        mock_llm.generate.return_value = mock_response_good
        
        council = EditorialCouncil(llm_client=mock_llm)
        result = council.evaluate_article("Title", "Summary")
        
        self.assertTrue(result.is_approved)
        self.assertGreaterEqual(result.average_score, 4.0)

        # Scenario 2: Low Score (Skeptic hates it)
        mock_response_bad = {
          "council_assessments": [
            {"role": "Científico", "score": 4, "observation": "ok"},
            {"role": "Escéptico", "score": 1, "observation": "Hype!"}, # < 2 fail
            {"role": "Curioso", "score": 4, "observation": "ok"},
            {"role": "Editor", "score": 3, "observation": "meh"}
          ],
          "editorial_synthesis": {},
          "editor_approval": "No, requiere cambios"
        }
        mock_llm.generate.return_value = mock_response_bad
        
        result_bad = council.evaluate_article("Bad Title", "Summary")
        self.assertFalse(result_bad.is_approved)
        self.assertEqual(result_bad.scores["Escéptico"], 1)

if __name__ == "__main__":
    unittest.main()
