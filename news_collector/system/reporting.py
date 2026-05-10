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
        # B-07 / F-0017: Add exported_at so consumers can detect stale data
        export_payload["exported_at"] = datetime.now(timezone.utc).isoformat()

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
