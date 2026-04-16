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

import sys


def main() -> None:
    import warnings

    warnings.warn(
        "main.py is deprecated. Use 'make run-local' or "
        "'python scripts/run_collector.py' instead. "
        "See docs/RUNBOOK_LOCAL_DEV.md.",
        DeprecationWarning,
        stacklevel=1,
    )
    sys.stderr.write(
        "\n[DEPRECATED] main.py is no longer the canonical entry point.\n"
        "Use one of the following instead:\n"
        "  make run-local\n"
        "  python scripts/run_collector.py\n\n"
        "See docs/RUNBOOK_LOCAL_DEV.md for the full development workflow.\n"
    )
    sys.exit(1)


if __name__ == "__main__":
    main()
