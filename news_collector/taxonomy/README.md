# Tag Taxonomy System

This directory contains the configuration and logic for the Noticiencias Tag Normalizer, which ensures all article tags are consistent, deduplicated, and semantically meaningful.

## Pipeline Architecture

The normalization process follows a strict pipeline:

1.  **Sanitization** (`sanitize_tags`):
    - **Basic Normalization**: Trims whitespace, lowercases, and replaces hyphens/underscores with spaces.
    - **Orthography Correction** (`orthography.yml`): Fixes spelling, accents, and grammar (e.g., `energia oscura` -> `energía oscura`).
    - **Semantic Aliasing** (`tags.yml`): Maps synonyms and abbreviations to canonical terms (e.g., `ia` -> `inteligencia artificial`).
    - **Deduplication**: Merges near-duplicates (ignoring accents/case) and preserves the first occurrence.
    - **Filtering**: Removes Stop Tags, enforces min/max length (unless whitelisted), and truncates to max tags per article (8).

2.  **Validation** (`validate_tags`):
    - Checks against strict regex `^[a-z0-9áéíóúüñ\s]+$`.
    - Flags any remaining stop tags or malformed tags.
    - Returns `needs_review=True` if manual intervention is required.

## Configuration Files

- `tags.yml`: **Source of Truth**. Contains semantic aliases (`alias_map`), stop tags, whitelist, and limits.
- `orthography.yml`: Contains orthographic corrections (`corrections`).

## Usage

```python
from news_collector.taxonomy.normalizer import TagNormalizer

normalizer = TagNormalizer()
result = normalizer.sanitize_tags(["ia", "Energia-Oscura"])
print(result.tags)
# Output: ['energía oscura', 'inteligencia artificial']

val_result = normalizer.validate_tags(result.tags)
if val_result.needs_review:
    print("Warning: Manual review needed")
```

## Backfilling

Use the CLI tool to clean existing content:

```bash
# Dry run (default)
python tools/backfill_tags.py

# Apply changes
python tools/backfill_tags.py --apply
```
