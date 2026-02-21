#!/usr/bin/env python3
import logging
import os
import sys

# Ensure project root is in path
sys.path.append(os.getcwd())

from news_collector.enrichment.strategy_optimizer import strategy_optimizer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main():
    logger.info("Generating Adaptive Enrichment Report...")

    try:
        report_content = strategy_optimizer.generate_report()

        output_path = "ADAPTIVE_ENRICHMENT_REPORT.md"
        with open(output_path, "w") as f:
            f.write(report_content)

        logger.info(f"Report generated successfully: {output_path}")

    except Exception as e:
        logger.error(f"Failed to generate report: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
