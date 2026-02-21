#!/usr/bin/env python3
"""
Context Validation Gate
Validates that context/MODULE_INDEX.md and context/modules/*.md are in sync.
- Every module context referenced in MODULE_INDEX.md must exist.
- No duplicate contexts in MODULE_INDEX.md.
- Every context/modules/*.md file must be referenced in MODULE_INDEX.md (no orphans).
"""

import glob
import os
import re
import sys


def _check_duplicates(extracted_paths):
    seen = set()
    duplicates = set()
    has_errors = False
    for path in extracted_paths:
        norm_path = os.path.normpath(path)
        if norm_path in seen:
            duplicates.add(norm_path)
            has_errors = True
        seen.add(norm_path)

    if duplicates:
        print("Error: Duplicate context paths found in MODULE_INDEX.md:")
        for d in sorted(duplicates):
            print(f"  - {d}")
    return seen, has_errors

def _validate_referenced_files(seen, existing_files_norm):
    missing_files = []
    has_errors = False
    for path in seen:
        if path not in existing_files_norm:
            missing_files.append(path)
            has_errors = True

    if missing_files:
        print("Error: Referenced context files are missing:")
        for m in sorted(missing_files):
            print(f"  - {m}")
    return has_errors

def _validate_orphans(seen, existing_files_norm):
    orphans = []
    has_errors = False
    for existing in existing_files_norm:
        if existing not in seen:
            orphans.append(existing)
            has_errors = True

    if orphans:
        print("Error: Orphaned context files found (not referenced in MODULE_INDEX.md):")
        for o in sorted(orphans):
            print(f"  - {o}")
    return has_errors

def main():
    has_errors = False

    # 1. Parse MODULE_INDEX.md
    index_path = "context/MODULE_INDEX.md"
    if not os.path.exists(index_path):
        print(f"Error: {index_path} not found.")
        sys.exit(1)

    with open(index_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Extract Context: ... paths
    # Matches optional leading whitespace and optional "-" before "Context:"
    extracted_paths = re.findall(r"^\s*(?:-\s*)?Context:\s*(context/modules/[\w\-\.]+\.md)", content, re.MULTILINE)

    if not extracted_paths:
        print("Error: No Context paths found in MODULE_INDEX.md. Check the format or regex.")
        sys.exit(1)

    # 2. Find all context/modules/*.md
    existing_files = glob.glob("context/modules/*.md")
    existing_files_norm = {os.path.normpath(p) for p in existing_files}

    # 3. Validate no duplicate contexts
    seen, dup_errors = _check_duplicates(extracted_paths)
    if dup_errors:
        has_errors = True

    # 4. Validate referenced files exist
    if _validate_referenced_files(seen, existing_files_norm):
        has_errors = True

    # 5. Validate no orphans
    if _validate_orphans(seen, existing_files_norm):
        has_errors = True

    if has_errors:
        print("\nContext validation failed. Please fix the above errors.")
        sys.exit(1)

    print("Context validation passed.")

if __name__ == "__main__":
    main()
