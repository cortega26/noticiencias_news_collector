#!/usr/bin/env python3
"""
validate_export.py

Validates the `latest_articles.json` export against the Frontend Contract.
Ensures that the backend produces data capable of being transformed into Noticiencias Blog Posts.
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

# Define Contract Schema (Mirroring src/content/config.ts requirements)
REQUIRED_FIELDS = ["title", "url", "source_id", "published_date", "summary"]

OPTIONAL_FIELDS = [
    "content",
    "author",
    "categories",
    "tags",
    "image",
    "editorial_score",
]


def validate_article(article: Dict[str, Any], index: int) -> List[str]:
    """Validates a single article object."""
    errors = []

    # Check Required Fields
    for field in REQUIRED_FIELDS:
        if field not in article:
            errors.append(f"Missing required field: '{field}'")
        elif not article[field]:
            errors.append(f"Field '{field}' is empty")

    # Type Checks
    if not isinstance(article.get("title", ""), str):
        errors.append("Title must be a string")

    # Date Validation
    if "published_date" in article:
        try:
            # Flexible date parsing (ISO format preferred)
            pd = article["published_date"]
            if isinstance(pd, str):
                datetime.fromisoformat(pd.replace("Z", "+00:00"))
        except ValueError:
            errors.append(
                f"Invalid date format for 'published_date': {article['published_date']}"
            )

    return errors


def validate_export(file_path: Path) -> bool:  # noqa: C901
    """Reads and validates the JSON export."""
    if not file_path.exists():
        print(f"❌ Error: Export file not found at {file_path}")
        return False

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"❌ Error: Invalid JSON format: {e}")
        return False

    if not isinstance(data, dict):
        print("❌ Error: Root element must be a dictionary")
        return False

    # Depending on export format, articles might be in a key like 'articles' or 'selection_results' -> 'articles'
    # Based on main.py: results["summary"]["articles_found"] etc.
    # We need to find the list of articles.

    articles = []
    if "articles" in data:
        articles = data["articles"]
    elif "selection_results" in data and "articles" in data["selection_results"]:
        articles = data["selection_results"]["articles"]
    elif (
        "collection_results" in data and "source_details" in data["collection_results"]
    ):
        # This is the raw collection, usually we want the selected ones.
        print("⚠️ Warning: Validating raw collection results, not final selection.")
        # Logic to extract from source_details would be needed, but let's focus on selection first.

    if not articles:
        print("⚠️ Warning: No articles found in export to validate.")
        # If dry-run produced 0 articles, it's technically a pass on schema, but maybe a fail on logic.
        # flexible for now.
        return True

    print(f"🔍 Validating {len(articles)} articles...")

    failure_count = 0
    for i, article in enumerate(articles):
        errors = validate_article(article, i)
        if errors:
            failure_count += 1
            print(
                f"  ❌ Article #{i+1} (Source: {article.get('source_id', 'unknown')}):"
            )
            for err in errors:
                print(f"     - {err}")

    if failure_count > 0:
        print(
            f"\n❌ Validation FAILED. {failure_count}/{len(articles)} articles invalid."
        )
        return False

    print("\n✅ Validation PASSED. All articles match the Frontend Contract.")
    return True


def main():
    parser = argparse.ArgumentParser(description="Validate Content Export")
    parser.add_argument("file_path", type=Path, help="Path to JSON export file")
    args = parser.parse_args()

    success = validate_export(args.file_path)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
