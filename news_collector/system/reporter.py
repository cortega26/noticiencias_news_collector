"""SessionReporter — generates session reports for the collection pipeline.

Extracted from reporting.generate_session_report to give the reporting
concern its own class with explicit dependencies.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from news_collector.config.sources import ALL_SOURCES
from news_collector.observability.enrichment_metrics_store import enrichment_metrics
from news_collector.system.source_health import serialize_source_health_report


class SessionReporter:
    """Generates structured session reports with performance metrics.

    Takes a reference to the system (duck-typed) to access:
        system_id, start_time, logger
    """

    def __init__(self, system: Any) -> None:
        self.system = system

    def generate_report(
        self,
        collection_results: Dict[str, Any],
        scoring_results: Dict[str, Any],
        selection_results: Dict[str, Any],
        session_id: str,
    ) -> Dict[str, Any]:
        """Build a full session report — same logic as reporting.generate_session_report."""
        end_time = datetime.now(timezone.utc)
        duration = (end_time - self.system.start_time).total_seconds()

        report: Dict[str, Any] = {
            "schema_version": 2,
            "session_info": {
                "session_id": session_id,
                "system_id": self.system.system_id,
                "start_time": self.system.start_time.isoformat(),
                "end_time": end_time.isoformat(),
                "duration_seconds": duration,
            },
            "collection_results": collection_results,
            "scoring_results": scoring_results,
            "selection_results": selection_results,
            "performance_metrics": {
                "total_duration_seconds": duration,
                "articles_per_second": (
                    collection_results.get("collection_summary", {}).get(
                        "articles_found", 0
                    )
                    / max(duration, 1)
                ),
                "sources_per_minute": (
                    collection_results.get("collection_summary", {}).get(
                        "sources_processed", 0
                    )
                    / max(duration / 60, 1)
                ),
                "success_rate_percent": collection_results.get(
                    "collection_summary", {}
                ).get("success_rate_percent", 0),
            },
            "summary": {
                "sources_processed": collection_results.get(
                    "collection_summary", {}
                ).get("sources_processed", 0),
                "articles_found": collection_results.get("collection_summary", {}).get(
                    "articles_found", 0
                ),
                "articles_saved": collection_results.get("collection_summary", {}).get(
                    "articles_saved", 0
                ),
                "articles_scored": scoring_results.get("statistics", {}).get(
                    "articles_scored", 0
                ),
                "final_selection_count": selection_results.get("selected_count", 0),
            },
        }

        try:
            source_details = collection_results.get("source_details", {})
            health_data = serialize_source_health_report(
                source_details,
                source_configs=ALL_SOURCES,
                metrics_by_source=enrichment_metrics.get_all_metrics(),
                last_run=datetime.now(timezone.utc),
            )

            export_path = Path("data/exports/source_health.json")
            export_path.parent.mkdir(parents=True, exist_ok=True)
            export_path.write_text(json.dumps(health_data, indent=2))
        except (OSError, TypeError) as e:
            self.system.logger.create_module_logger("system.reporting").warning(
                f"Failed to export source health data: {e}"
            )

        return report
