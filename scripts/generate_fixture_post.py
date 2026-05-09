"""
generate_fixture_post.py — writes a minimal valid AstroPost MDX fixture file.

Used by the publication smoke-test CI workflow to verify that the current
AstroPost contract produces a file that passes the front-end `validate:content`
check.  The fixture is written to a path supplied via --output; the caller is
responsible for cleaning it up afterwards.

Usage:
    python scripts/generate_fixture_post.py --output ../noticiencias/src/content/posts/_smoke-test.md
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure repo root is importable when run as a script
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from news_collector.logic.workflows.frontend_publication_validation import (  # noqa: E402
    build_fixture_post,
    render_fixture_markdown,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a minimal AstroPost fixture file."
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Destination path for the fixture .md file",
    )
    args = parser.parse_args()

    content = render_fixture_markdown(build_fixture_post())

    output_path: Path = args.output.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")
    print(f"[fixture] written to {output_path}")


if __name__ == "__main__":
    main()
