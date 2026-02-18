import json
import sys
from pathlib import Path

# Add project root to path
from pathlib import Path
import os
import sys

BASE_DIR = Path(os.environ.get('NEWS_COLLECTOR_PATH', Path(__file__).resolve().parents[1])).resolve()
sys.path.insert(0, str(BASE_DIR))

from news_collector.components.editorial.ai_editor import EditorAgent


def main():
    print("🚀 Starting manual publication for ID 206...")

    # 1. Load latest articles
    json_path = Path("data/exports/latest_articles.json")
    with open(json_path, "r") as f:
        articles = json.load(f)

    # Access the list under "articles" key
    article_list = articles.get("articles", [])
    target_article = next((a for a in article_list if str(a.get("id")) == "206"), None)

    if not target_article:
        print("❌ ID 206 not found in latest_articles.json")
        sys.exit(1)

    print(f"✅ Found article: {target_article['title']}")

    # 2. Setup Editor
    # Use the unified provider URL and correct model
    editor = EditorAgent(
        api_url="http://localhost:11434/api/generate", model="llama3.2:latest"
    )

    # Load Prompts manually because we want strict control
    import yaml

    with open("config/prompts.yaml", "r") as f:
        prompts = yaml.safe_load(f)

    translator_prompt = prompts["translator"]["system"]

    # 3. Translate Title (Phase 1 strict)
    print("\n--- Phase 1: Translating Title ---")
    english_title = target_article["title"]
    # We ask ONLY for the title translation to be precise
    title_translation_prompt = f"Translate the following title to Spanish. Do not add quotes or extra text.\n\n{english_title}"

    translated_title = editor._send_prompt(
        title_translation_prompt, system=translator_prompt
    )
    translated_title = translated_title.strip().strip('"')
    print(f"Original: {english_title}")
    print(f"Translated: {translated_title}")

    # 4. Process Body (Recovery from Cache or Regenerate)
    print("\n--- Phase 1 & 2: Processing Body ---")

    # Check cache for Stage 2 (Editorial)
    cache_path = Path("temp/cache/206_stage2_editorial.txt")
    if cache_path.exists():
        print(f"✅ Found cached Stage 2 content: {cache_path}")
        edited_content = cache_path.read_text(encoding="utf-8")
        # Remove the first line if it looks like a title (simple heuristic)
        # Because we want to inject our NEW translated title
        lines = edited_content.splitlines()
        if (
            lines and "**" in lines[0]
        ):  # Often titles are bolded in the body or just text
            # Actually, let's keep the body as is, but rely on frontmatter for the main title.
            # The markdown body often contains a heading.
            pass
    else:
        print("⚠️ Cache not found. Regenerating body...")
        input_text = (
            f"Title: {english_title}\nContent: {target_article.get('content', '')}"
        )

        # Phase 1: Translate Content
        translated_content = editor._send_prompt(input_text, system=translator_prompt)

        # Phase 2: Edit Content
        edited_content = editor._adapt_editorial(translated_content)
        edited_content = editor._extract_markdown_content(edited_content)

    # 5. Assemble Output (Skip Phase 3 Headlines)
    print("\n--- Constructing File ---")

    # Generate slug from English or Translated? Usually English slug is better for URLs but Spanish expected?
    # User provided URL: .../2026-01-27-article-206/
    # Wait, the user provided URL ends in `article-206`.
    # So I should force the filename to match that expectation if possible, or closely match.
    # Actually, `refinery_engine` uses `article-{id}` as fallback slug.
    # Let's use `article-206` as the slug to match that URL pattern if that's what "article-206" means.

    slug = "article-206"
    today = "2026-01-27"  # Force date to match user expectation
    filename = f"{today}-{slug}.md"

    # Construct Frontmatter
    frontmatter = f"""---
title: "{translated_title}"
date: {today}
author: "Noticiencias AI"
categories: ["Ciencia"]
tags: ["electridos", "materiales", "quimica"]
excerpt: "Un misterioso grupo de materiales llamados electridos podría revolucionar la química."
source_url: "{target_article.get('url')}"
refinery_id: "206"
---

{edited_content}
"""

    output_path = Path("/home/cortega26/noticiencias/src/content/posts") / filename
    output_path.write_text(frontmatter, encoding="utf-8")

    print(f"✅ Published to: {output_path}")


if __name__ == "__main__":
    main()
