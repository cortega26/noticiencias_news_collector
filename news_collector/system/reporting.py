"""
Modulo de Reporting.
Desacoplado de NewsCollectorSystem para reducir acoplamiento y tamaño de objeto Dios ("God Module").
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from news_collector.config import SCORING_CONFIG


def get_top_articles(
    system, limit: int = 10, category: Optional[str] = None
) -> List[Dict[str, Any]]:
    if not system.is_initialized:
        raise RuntimeError("Sistema no inicializado")

    try:
        if category:
            articles = system.db_manager.get_articles_by_category(category)
        else:
            articles = system.db_manager.get_articles_by_score(limit)

        articles_dicts = [article.to_dict() for article in articles]

        from news_collector.reranker import rerank_articles

        reranked = rerank_articles(
            articles_dicts,
            limit=limit,
            source_cap_percentage=SCORING_CONFIG.get("source_cap_percentage", 0.5),
            topic_cap_percentage=SCORING_CONFIG.get("topic_cap_percentage", 0.5),
            seed=SCORING_CONFIG.get("reranker_seed", 42),
        )

        return reranked

    except Exception as e:
        system.logger.log_error_with_context(
            e,
            {"operation": "get_top_articles", "limit": limit, "category": category},
        )
        raise


def export_latest_articles(
    system, file_path: Optional[str] = None, limit: int = 50
) -> Dict[str, Any]:
    if not system.is_initialized:
        raise RuntimeError("Sistema no inicializado")

    try:
        articles = system.db_manager.get_articles_by_score(
            limit=limit, exclude_published=True
        )

        from news_collector.contracts.adapters import adapt_article_to_export
        from news_collector.contracts.export import ExportContractV2

        export_models = [adapt_article_to_export(art) for art in articles]

        contract = ExportContractV2(
            generated_at=datetime.now(timezone.utc).isoformat(),
            article_count=len(export_models),
            articles=export_models,
        )

        export_payload = contract.model_dump()

        if file_path:
            path_obj = (
                Path(json.dumps(file_path).strip('"'))
                if not isinstance(file_path, Path)
                else file_path
            )
            # Ensure we handle the path correctly whether string or Path
            path_obj = Path(file_path)
            path_obj.parent.mkdir(parents=True, exist_ok=True)

            with open(path_obj, "w", encoding="utf-8") as f:
                json.dump(export_payload, f, indent=2, ensure_ascii=False)

            if system.logger:
                system.logger.create_module_logger("system").info(
                    f"Exported {len(export_models)} articles to {path_obj}"
                )

        return export_payload

    except Exception as e:
        system.logger.log_error_with_context(e, {"operation": "export_latest_articles"})
        raise


def get_system_statistics(system) -> Dict[str, Any]:
    if not system.is_initialized:
        raise RuntimeError("Sistema no inicializado")

    try:
        db_health = system.db_manager.get_health_status()
        daily_stats = system.db_manager.get_daily_stats()

        system_uptime = (datetime.now(timezone.utc) - system.start_time).total_seconds()

        return {
            "system_info": {
                "system_id": system.system_id,
                "start_time": system.start_time.isoformat(),
                "uptime_seconds": system_uptime,
                "is_healthy": db_health.get("status") == "healthy",
            },
            "database_health": db_health,
            "daily_statistics": daily_stats,
            "performance_summary": {},
        }
    except Exception as e:
        system.logger.log_error_with_context(e, {"operation": "get_system_statistics"})
        raise


def generate_session_report(
    system,
    collection_results: Dict[str, Any],
    scoring_results: Dict[str, Any],
    selection_results: Dict[str, Any],
    session_id: str,
) -> Dict[str, Any]:
    end_time = datetime.now(timezone.utc)
    duration = (end_time - system.start_time).total_seconds()

    report = {
        "schema_version": 2,
        "session_info": {
            "session_id": session_id,
            "system_id": system.system_id,
            "start_time": system.start_time.isoformat(),
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
            "sources_processed": collection_results.get("collection_summary", {}).get(
                "sources_processed", 0
            ),
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
        health_data = {}
        source_details = collection_results.get("source_details", {})
        for source_id, result in source_details.items():
            success = result.get("success", False)
            saved = result.get("articles_saved", 0)

            health_data[source_id] = {
                "last_run": datetime.now(timezone.utc).isoformat(),
                "feed_ok": success,
                "pipeline_ok": True,  # If we have a result here, pipeline ran
                "content_ok": saved > 0,
                "content_mode": result.get("content_mode", "unknown"),
                "articles_found": result.get("articles_found", 0),
                "articles_saved": saved,
                "last_error_message": result.get("error_message"),
                "latency": result.get("processing_time", 0),
            }

        export_path = Path("data/exports/source_health.json")
        export_path.parent.mkdir(parents=True, exist_ok=True)
        export_path.write_text(json.dumps(health_data, indent=2))
    except Exception:  # noqa: S110
        # Fail silently to avoid crashing report generation
        pass

    return report
