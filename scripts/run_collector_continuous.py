#!/usr/bin/env python3
"""
Continuous Collector Runner
===========================
Executes the news collector in an infinite loop, ensuring clean process separation
to prevent memory leaks (especially from Playwright/Chromium).

Configuration:
    COLLECTION_INTERVAL_SECONDS (int): Seconds to sleep between runs (default: 600)
    MAX_CONSECUTIVE_FAILURES (int): Max allowed consecutive failures before exit (default: 5)
"""

import logging
import os
import subprocess
import sys
import time

# Setup basic logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("continuous_runner")
_TRUTHY_VALUES = {"1", "true", "yes", "on"}


def _is_smoke_mode_enabled() -> bool:
    return os.getenv("NOTICIENCIAS_SMOKE", "").strip().lower() in _TRUTHY_VALUES


def _build_cycle_command(smoke_mode: bool) -> list[str]:
    if smoke_mode:
        return [sys.executable, "scripts/run_collector_smoke.py"]
    return [sys.executable, "scripts/run_collector.py"]


def main() -> int:
    interval = int(os.getenv("COLLECTION_INTERVAL_SECONDS", "600"))
    smoke_mode = _is_smoke_mode_enabled()
    default_max_failures = "1" if smoke_mode else "5"
    max_failures = int(os.getenv("MAX_CONSECUTIVE_FAILURES", default_max_failures))
    consecutive_failures = 0

    logger.info("🚀 Starting Continuous Collector")
    logger.info(f"   Mode: {'smoke' if smoke_mode else 'continuous'}")
    logger.info(f"   Interval: {interval} seconds")
    logger.info(f"   Max Failures: {max_failures}")
    logger.info(f"   Environment: {os.getenv('RUN_ENVIRONMENT', 'production')}")

    while True:
        start_time = time.time()
        cycle_succeeded = False
        logger.info("--------------------------------------------------")
        logger.info("🎬 Starting new collection cycle...")

        try:
            # Run collector as subprocess to ensure clean memory slate per run
            result = subprocess.run(
                _build_cycle_command(smoke_mode),
                capture_output=False,  # Let it print to stdout/stderr
                check=False,
            )

            duration = time.time() - start_time

            if result.returncode == 0:
                logger.info(f"✅ Cycle completed successfully in {duration:.2f}s")
                consecutive_failures = 0
                cycle_succeeded = True
            else:
                consecutive_failures += 1
                logger.error(
                    f"❌ Cycle failed with return code {result.returncode} ({duration:.2f}s)"
                )
                logger.warning(
                    f"   Consecutive failures: {consecutive_failures}/{max_failures}"
                )

        except Exception as e:
            consecutive_failures += 1
            logger.error(f"❌ infrastructure error: {e}")

        # Check health
        if consecutive_failures >= max_failures:
            logger.critical(
                "🚨 Max consecutive failures reached. Aborting continuous mode."
            )
            return 1

        if smoke_mode:
            if cycle_succeeded:
                logger.info(
                    "🧪 Smoke mode finished after one bounded cycle (no sleep)."
                )
                return 0
            logger.error("🧪 Smoke mode cycle failed.")
            return 1

        # Wait for next cycle
        logger.info(f"💤 Sleeping for {interval} seconds...")
        time.sleep(interval)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        logger.info("🛑 Continuous runner stopped by user.")
        sys.exit(130)
