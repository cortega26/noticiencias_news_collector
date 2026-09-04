"""
Modulo de Reporting.
Desacoplado de NewsCollectorSystem para reducir acoplamiento y tamaño de objeto Dios ("God Module").
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from news_collector.config.settings import get_runtime_config

# Oversample factor for the export shortlist (plan 068): the diversity
# caps below can only filter, so more candidates are fetched than exported
# to keep the shortlist full under realistic source/topic concentration.
# Extreme single-source dominance still yields fewer than `limit` — the
# caps working as designed, never an error.
EXPORT_RERANK_OVERSAMPLE = 3


def get_top_articles(
    system, limit: int = 10, category: Optional[str] = None
) -> List[Dict[str, Any]]:
    if not system.is_initialized:
        raise RuntimeError("Sistema no inicializado")

    try:
        scoring_config = get_runtime_config().scoring_config
        if category:
            articles = system.db_manager.get_articles_by_category(category)
        else:
            articles = system.db_manager.get_articles_by_score(
                limit,
                max_age_days=scoring_config.get("candidate_max_age_days", 30),
            )

        articles_dicts = [article.to_dict() for article in articles]

        from news_collector.reranker import rerank_articles

        reranked = rerank_articles(
            articles_dicts,
            limit=limit,
            source_cap_percentage=scoring_config.get("source_cap_percentage", 0.5),
            topic_cap_percentage=scoring_config.get("topic_cap_percentage", 0.5),
            seed=scoring_config.get("reranker_seed", 42),
        )

        return reranked

    except Exception as e:
        system.logger.log_error_with_context(
            e,
            {"operation": "get_top_articles", "limit": limit, "category": category},
        )
        raise


def _rank_dict_for_export(article: Any) -> Dict[str, Any]:
    """Build the reranker input for one ORM article.

    `to_dict()` plus safely-attached `article_metadata` (detached/expired
    sessions yield `{}` instead of raising) and `None`-hardened sort keys —
    the reranker's `(final_score, published_date, source)` tuple would
    `TypeError` on `None` ties.
    """
    payload: Dict[str, Any] = article.to_dict()
    try:
        metadata = article.article_metadata or {}
    except Exception:
        metadata = {}
    payload["article_metadata"] = metadata if isinstance(metadata, dict) else {}
    payload["final_score"] = payload.get("final_score") or 0.0
    payload["published_date"] = payload.get("published_date") or ""
    return payload


def export_latest_articles(
    system, file_path: Optional[str] = None, limit: int = 50
) -> Dict[str, Any]:
    if not system.is_initialized:
        raise RuntimeError("Sistema no inicializado")

    try:
        scoring_config = get_runtime_config().scoring_config
        articles = system.db_manager.get_articles_by_score(
            limit=limit * EXPORT_RERANK_OVERSAMPLE,
            exclude_published=True,
            max_age_days=scoring_config.get("candidate_max_age_days", 30),
        )

        from news_collector.contracts.adapters import adapt_article_to_export
        from news_collector.contracts.export import ExportContractV2
        from news_collector.reranker import rerank_articles

        # Diversity caps (plan 068): same operator-tunable knobs as
        # `get_top_articles`, so the publish shortlist cannot be filled by
        # a single dominant source/topic. Deterministic via configured seed.
        rank_inputs = [_rank_dict_for_export(article) for article in articles]
        reranked = rerank_articles(
            rank_inputs,
            limit=limit,
            source_cap_percentage=scoring_config.get("source_cap_percentage", 0.5),
            topic_cap_percentage=scoring_config.get("topic_cap_percentage", 0.5),
            seed=scoring_config.get("reranker_seed", 42),
        )
        by_id = {
            payload["id"]: article
            for article, payload in zip(articles, rank_inputs, strict=True)
            if payload.get("id") is not None
        }
        selected = [
            by_id[payload["id"]] for payload in reranked if payload["id"] in by_id
        ]

        export_models = [adapt_article_to_export(art) for art in selected]

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
