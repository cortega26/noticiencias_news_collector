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

import os
import time
import subprocess
import logging
import sys
from datetime import datetime

# Setup basic logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("continuous_runner")

def main():
    interval = int(os.getenv("COLLECTION_INTERVAL_SECONDS", "600"))
    max_failures = int(os.getenv("MAX_CONSECUTIVE_FAILURES", "5"))
    consecutive_failures = 0
    
    logger.info("🚀 Starting Continuous Collector")
    logger.info(f"   Interval: {interval} seconds")
    logger.info(f"   Max Failures: {max_failures}")
    logger.info(f"   Environment: {os.getenv('RUN_ENVIRONMENT', 'production')}")

    while True:
        start_time = time.time()
        logger.info("--------------------------------------------------")
        logger.info("🎬 Starting new collection cycle...")
        
        try:
            # Run collector as subprocess to ensure clean memory slate per run
            result = subprocess.run(
                [sys.executable, "scripts/run_collector.py"],
                capture_output=False, # Let it print to stdout/stderr
                check=False
            )
            
            duration = time.time() - start_time
            
            if result.returncode == 0:
                logger.info(f"✅ Cycle completed successfully in {duration:.2f}s")
                consecutive_failures = 0
            else:
                consecutive_failures += 1
                logger.error(f"❌ Cycle failed with return code {result.returncode} ({duration:.2f}s)")
                logger.warning(f"   Consecutive failures: {consecutive_failures}/{max_failures}")

        except Exception as e:
            consecutive_failures += 1
            logger.error(f"❌ infrastructure error: {e}")
        
        # Check health
        if consecutive_failures >= max_failures:
            logger.critical("🚨 Max consecutive failures reached. Aborting continuous mode.")
            sys.exit(1)
            
        # Wait for next cycle
        logger.info(f"💤 Sleeping for {interval} seconds...")
        time.sleep(interval)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("🛑 Continuous runner stopped by user.")
        sys.exit(0)
