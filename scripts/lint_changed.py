#!/usr/bin/env python3
"""
Lint Changed Files
Computes changed Python files vs origin/main (fallback to git diff --name-only).
Runs ruff only on those files.
"""

import os
import subprocess
import sys


def get_changed_files():
    """Get list of changed Python files."""
    try:
        # Try comparing against origin/main first
        result = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=d", "origin/main...HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        files = result.stdout.strip().split("\n")

        # If that's empty or fails, include unstaged and staged changes too
        if not any(f.strip() for f in files):
            raise subprocess.CalledProcessError(1, ["git", "diff"])

    except subprocess.CalledProcessError:
        # Fallback to local unstaged/staged changes combined
        try:
            # Staged changes
            staged = (
                subprocess.run(
                    ["git", "diff", "--name-only", "--cached", "--diff-filter=d"],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                .stdout.strip()
                .split("\n")
            )

            # Unstaged changes
            unstaged = (
                subprocess.run(
                    ["git", "diff", "--name-only", "--diff-filter=d"],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                .stdout.strip()
                .split("\n")
            )

            # Untracked files (but not ignored)
            untracked = (
                subprocess.run(
                    ["git", "ls-files", "--others", "--exclude-standard"],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                .stdout.strip()
                .split("\n")
            )

            files = list(set(staged + unstaged + untracked))
        except subprocess.CalledProcessError as e:
            print(f"Error getting changed files: {e}")
            sys.exit(1)

    return [f for f in files if f.endswith(".py") and os.path.exists(f)]


def main():
    changed_python_files = get_changed_files()

    if not changed_python_files:
        print("No Python changes detected.")
        sys.exit(0)

    print(f"Running ruff on {len(changed_python_files)} changed Python file(s)...")

    # Run ruff check on the specific files
    ruff_cmd = [sys.executable, "-m", "ruff", "check"] + changed_python_files

    try:
        result = subprocess.run(
            ruff_cmd, capture_output=False
        )  # Let it print to stdout/stderr directly
        if result.returncode != 0:
            print(
                f"\nRuff found issues in changed files. (Exit code: {result.returncode})"
            )
            sys.exit(result.returncode)
    except FileNotFoundError:
        print("Error: ruff is not installed or not found in the current environment.")
        sys.exit(1)

    print("Linting passed for changed files.")


if __name__ == "__main__":
    main()
