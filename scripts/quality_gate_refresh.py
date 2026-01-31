
import sys
import os
import json
import time
import argparse
from pathlib import Path
import re

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(PROJECT_ROOT))

# Imports from project
try:
    from news_collector.components.editorial.ai_editor import EditorAgent
except ImportError as e:
    print(f"Error importing project modules: {e}")
    sys.exit(1)

GOLDEN_DIR = PROJECT_ROOT / "quality_gate" / "golden"

def main():
    print("⚠️  WARNING: You are about to regenerate Quality Gate snapshots.")
    print("   This involves calling the LLM and overwriting authoritative baselines.")
    print("   Review the git diffs CAREFULLY before committing.\n")
    
    # Simple confirmation delay
    print("Starting in 3 seconds...", end="", flush=True)
    time.sleep(3)
    print(" GO.\n")

    agent = EditorAgent(
        api_url=os.getenv("OLLAMA_API_URL", "http://localhost:11434/api/generate"),
        model=os.getenv("OLLAMA_MODEL", "llama3.2:latest"),
    )
    # Increase timeout for generation
    agent.provider.timeout = 300

    cases = sorted([d for d in GOLDEN_DIR.iterdir() if d.is_dir()])
    
    for case_dir in cases:
        print(f">> 🔄 Refreshing: {case_dir.name}")
        
        input_path = case_dir / "input.txt"
        if not input_path.exists():
            print(f"   Skipping (no input.txt)")
            continue
            
        with open(input_path, "r") as f:
            content_text = f.read()

        try:
            full_output = agent.process_article(content_text)
        except Exception as e:
            print(f"   ❌ Generation failed: {e}")
            sys.exit(1)

        # Parse headlines from frontmatter to store in structured format
        headlines = {}
        title_match = re.search(r'title: "(.*?)"', full_output)
        if title_match: headlines["directo"] = title_match.group(1)
        
        q_match = re.search(r'question: "(.*?)"', full_output)
        if q_match: headlines["pregunta"] = q_match.group(1)
            
        b_match = re.search(r'benefit: "(.*?)"', full_output)
        if b_match: headlines["relevancia"] = b_match.group(1)

        snapshot_data = {
            "content": full_output,
            "headlines": headlines
        }
        
        snap_path = case_dir / "snapshot.json"
        with open(snap_path, "w", encoding="utf-8") as f:
            json.dump(snapshot_data, f, indent=2, ensure_ascii=False)
            
        print(f"   ✅ Saved snapshot to {snap_path.name}")

    print("\n✨ Refresh Complete. Run 'make quality-gate' to verify.")

if __name__ == "__main__":
    main()
