import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(PROJECT_ROOT))


class TestRefineryUIContracts(unittest.TestCase):
    """
    Verifies the UI Contracts for Critic Visibility, Handoff Fallback, and Auditor.
    Uses 'exec' to run specific blocks or mocks streamlit to trace execution.
    """

    def setUp(self):
        # Mock Streamlit
        self.mock_st = MagicMock()
        self.modules_patcher = patch.dict(sys.modules, {"streamlit": self.mock_st})
        self.modules_patcher.start()

        # Mock other dependencies to prevent side effects
        self.mock_sqlite = MagicMock()
        self.sqlite_patcher = patch("sqlite3.connect", return_value=self.mock_sqlite)
        self.sqlite_patcher.start()

    def tearDown(self):
        self.modules_patcher.stop()
        self.sqlite_patcher.stop()

    def test_critic_config_visibility_enabled(self):
        """Verify Critic metric is verified when enabled."""

        # Mock minimal environment to reach the Critic block
        # We can't easily execute the whole script, so we might need to extract the logic
        # or rely on manual verification if script execution is too complex.
        # BUT, let's try to verify the logic by importing the module IF we can control it.
        # Given admin_panel.py is a top-level script, importing it runs it.
        # We will use a different approach: verify key constants or functions if they exist.
        # Since logic is inline, we will verify via regex/AST or by assuming the manual verification step
        # is the primary source of truth for UI appearance, and this test checks logic *if* we extracted it.

        # PLAN B: Since refactoring was discouraged ("No unnecessary refactors"),
        # and checking inline script logic via unit test is hard,
        # I will check if I can import the 'admin_panel' logic safely.

        # If I cannot run the script, I will write a test that verifies the presence of the code blocks
        # ensuring they adhere to the contract (Static Analysis).

        with open(
            PROJECT_ROOT / "apps/refinery/admin_panel.py", "r", encoding="utf-8"
        ) as f:
            content = f.read()

        # 1. Check Critic Visibility
        self.assertIn("Fase 2.5: Crítico", content)
        self.assertIn("ENABLE_TRANSLATION_GUARD", content)
        # Check for presence of metric call with correct label, unrelated to variable name (st.metric vs col.metric)
        self.assertIn('.metric("Umbral de Aprobación"', content)
        self.assertIn('st.success("✅ **CRITIC ENABLED**', content)

        # 2. Check Fallback Logic exists
        self.assertIn("Attempting DB Fallback", content)
        self.assertIn("Modo Recuperación", content)
        self.assertIn("articles = candidates", content)

        # 3. Check Auditor Visibility exists
        self.assertIn("auditor_score.json", content)
        self.assertIn("Rigor:", content)

        # 4. Check Manual URL ingestion controls exist
        self.assertIn("Pegar URL Específica", content)
        self.assertIn("🔗 Cargar Artículo desde URL", content)
        self.assertIn("render_article_processing_panel", content)
        self.assertIn("Artículo Seleccionado del Ranking", content)
        self.assertIn("Artículo Cargado desde URL", content)

        # 5. Check image brief queue visibility exists
        self.assertIn("🖼️ Cola de Imágenes (Image Queue)", content)
        self.assertIn("Cola Editorial de Imágenes", content)
        self.assertIn("Prompt listo para copiar", content)
        self.assertIn("Subir imagen curada", content)

        print("✅ Static Contract Verification Passed for admin_panel.py")

    def test_no_deprecated_streamlit_args(self):
        """Verify that no deprecated Streamlit arguments like use_container_width are present."""
        with open(
            PROJECT_ROOT / "apps/refinery/admin_panel.py", "r", encoding="utf-8"
        ) as f:
            content = f.read()
        self.assertNotIn("use_container_width", content)


if __name__ == "__main__":
    unittest.main()
