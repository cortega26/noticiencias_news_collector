# main.py  —  DEPRECATED
# ===========================================================================
# This entry point is deprecated and will be removed in a future release.
# Use the canonical entry points instead:
#
#   make run-local          — standard local run
#   make debug              — verbose/debug run
#   python scripts/run_collector.py [args]  — direct script invocation
#
# See docs/RUNBOOK_LOCAL_DEV.md for the full development workflow.
# ===========================================================================

import argparse
import json
import sys

from news_collector.exceptions import EXIT_INTERNAL, NewsCollectorError
from news_collector.system import create_system  # noqa: F401 — re-exported for compat


def handle_exception(exc: Exception) -> None:
    """Handle exception with structured JSON output and proper exit code."""
    if isinstance(exc, NewsCollectorError):
        exit_code = exc.exit_code
        category = exc.category
    else:
        exit_code = EXIT_INTERNAL
        category = "INTERNAL_ERROR"

    error_message = str(exc)

    print(
        json.dumps(
            {
                "status": "fatal_error",
                "error_message": error_message,
                "exit_code": exit_code,
                "error_category": category,
            }
        )
    )

    sys.stderr.write(
        f"\n❌ ERROR FATAL DEL SISTEMA\n"
        f"  Categoría: {category}\n"
        f"  (Código {exit_code})\n"
        f"  {error_message}\n"
    )

    sys.exit(exit_code)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="main.py",
        description=(
            "[DEPRECATED] News Collector entry point. "
            "Use 'make run-local' or 'python scripts/run_collector.py' instead."
        ),
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Run without saving data"
    )
    parser.parse_args()

    try:
        create_system()
    except Exception as exc:
        handle_exception(exc)


if __name__ == "__main__":
    main()
