
import sys
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent))

try:
    from noticiencias.config_manager import load_config

    config = load_config()

    print("✅ Configuration Loaded Successfully")
    print(f"GitHub Source Repo: {config.github.source_repo_url}")
    print(f"GitHub Target Repo: {config.github.target_repo_url}")
    print(f"GitHub User: {config.github.user_name}")
    print(f"Ollama URL: {config.ollama.api_url}")

    if config.github.token:
        print("✅ GitHub Token found (masked)")
    else:
        print("❌ GitHub Token NOT found")

except Exception as e:
    print(f"❌ Configuration Error: {e}")
