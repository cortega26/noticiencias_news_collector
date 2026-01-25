#!/usr/bin/env python3
"""
Audit Duplicates Script
-----------------------
Scans the published content directory for articles sharing the same 'refinery_id'.
This helps detect when the Canonical URL Integrity invariant has been violated.

Usage:
    python scripts/audit_duplicates.py --path apps/refinery/temp/target/src/content/posts
"""

import argparse
import re
from collections import defaultdict
from pathlib import Path

def audit_duplicates(posts_dir: Path):
    if not posts_dir.exists():
        print(f"❌ Directory not found: {posts_dir}")
        return

    print(f"🔍 Scanning {posts_dir}...")
    
    # Map ID -> List[Filename]
    id_map = defaultdict(list)
    
    # Regex to find refinery_id: "123"
    id_pattern = re.compile(r'refinery_id:\s*"([^"]+)"')

    for file_path in posts_dir.glob("*.md"):
        try:
            content = file_path.read_text(encoding="utf-8")
            match = id_pattern.search(content)
            if match:
                ref_id = match.group(1)
                id_map[ref_id].append(file_path.name)
        except Exception as e:
            print(f"⚠️ Error reading {file_path.name}: {e}")

    # Report
    duplicates_found = False
    print("\n--- Duplicate Report ---")
    for ref_id, files in id_map.items():
        if len(files) > 1:
            duplicates_found = True
            print(f"\n🚨 ID: {ref_id}")
            for f in sorted(files):
                print(f"   - {f}")

    if not duplicates_found:
        print("\n✅ No duplicates found. Canonical integrity checks passed.")
    else:
        print("\n❌ Duplicates detected! Please merge or delete the incorrect versions manually.")
        import sys
        sys.exit(1)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Audit published posts for duplicate IDs.")
    parser.add_argument("--path", type=str, default="apps/refinery/temp/target/src/content/posts", help="Path to posts directory")
    args = parser.parse_args()
    
    audit_duplicates(Path(args.path))
