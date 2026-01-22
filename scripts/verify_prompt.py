import importlib.util
import os
import sys


def import_module_from_path(module_name, file_path):
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


# 1. Mock 'src.utils.logger' because EditorAgent imports it
# We create a fake module so the import inside EditorAgent doesn't fail
from unittest.mock import MagicMock

mock_logger = MagicMock()
sys.modules["src"] = MagicMock()
sys.modules["src.utils"] = MagicMock()
sys.modules["src.utils.logger"] = mock_logger
mock_logger.setup_logger.return_value = MagicMock()

# 2. Import EditorAgent directly from file
file_path = os.path.join(
    os.getcwd(), "apps", "refinery", "src", "services", "editor_agent.py"
)
editor_agent_module = import_module_from_path("editor_agent_module", file_path)
EditorAgent = editor_agent_module.EditorAgent


def test_prompt_generation():
    print("🧪 Testing EditorAgent Prompt Generation...\n")

    # Mock data
    agent = EditorAgent("http://localhost:11434/api/generate", "mock-model")
    article = {
        "title": "Fusion Breakthrough",
        "summary": "Scientists achieved net gain.",
        "content": "Detailed technical content about lasers and plasma physics.",
        "image_url": "http://example.com/fusion.jpg",
    }

    # We want to see the prompt, but _send_prompt interacts with network.
    # We will override _send_prompt temporarily for this test
    original_send = agent._send_prompt

    def mock_send(prompt):
        print("✅ PROMPT GENERATED SUCCESSFULLY:")
        print("=" * 60)
        print(prompt)
        print("=" * 60)
        return "Mock response"

    agent._send_prompt = mock_send

    try:
        agent.process_article(article)
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    test_prompt_generation()
