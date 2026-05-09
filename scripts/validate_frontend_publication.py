"""Run the backend-driven frontend publication smoke validation."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from news_collector.logic.workflows.frontend_publication_validation import (  # noqa: E402
    run_frontend_publication_validation,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate a generated publication artifact against the frontend."
    )
    parser.add_argument(
        "--frontend-root",
        required=True,
        type=Path,
        help="Path to the checked-out frontend repository root",
    )
    parser.add_argument(
        "--summary-output",
        required=True,
        type=Path,
        help="Path where the machine-readable validation summary JSON will be written",
    )
    args = parser.parse_args()

    summary = run_frontend_publication_validation(
        args.frontend_root,
        summary_output_path=args.summary_output,
    )

    status = "passed" if summary.success else "failed"
    print(f"[publication-smoke] Frontend validation {status}")
    print(f"[publication-smoke] Summary: {args.summary_output.resolve()}")
    if not summary.success:
        print(
            "[publication-smoke] Failure class: "
            f"{summary.overall_failure_class or 'unknown'}"
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
