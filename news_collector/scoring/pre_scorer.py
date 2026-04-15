from typing import Any, Dict, List, Optional

from news_collector.config.settings import CONFIG
from news_collector.infrastructure.llm.factory import get_provider
from news_collector.infrastructure.llm.model_registry import get_model_for_stage
from news_collector.infrastructure.llm.rate_limiter import LLMRateLimiter
from news_collector.utils.logger import get_logger

logger = get_logger().create_module_logger(__name__)

# IMPORTANT: Do not use %d or %s for string interpolation in logging calls here.
# This project uses Loguru, which requires `{}` formatting (e.g. logger.info("... {}", var)).
# Using %s or %d will result in literal '%d' printing in the logs and cause regressions.

class PreScorer:
    """
    Evaluador preliminar que selecciona los mejores candidatos de un pool grande
    basándose en títulos y resúmenes antes de la extracción de texto completo.

    Rate-limit aware:
    - Checks the circuit breaker before attempting an LLM call.
    - Falls back to FIFO immediately when the breaker is open, avoiding
      wasted retries and blocking time.
    """

    def __init__(self, llm_client: Optional[Any] = None):
        if llm_client is None:
            model = get_model_for_stage("pre_scorer", config=CONFIG, logger=logger)
            self.llm = get_provider(
                config=CONFIG,
                api_url=CONFIG.ollama.api_url,
                model=model,
            )
        else:
            self.llm = llm_client
        self.model_name = self.llm.model

    def select_top_candidates(  # noqa: C901
        self, candidates: List[Dict[str, Any]], limit: int = 5, source_context: str = ""
    ) -> List[Dict[str, Any]]:
        """
        Analiza una lista de candidatos y retorna el subset top-ranked.

        Args:
            candidates: Lista de dicts con keys 'title', 'summary', 'url'.
            limit: Número de artículos a seleccionar.
            source_context: Nombre o descripción de la fuente para contexto.
        """
        if not candidates:
            return []

        if len(candidates) <= limit:
            logger.info(
                "PreScorer: Solicitados {}, disponibles {}. Retornando todos.",
                limit,
                len(candidates),
            )
            return candidates

        # --- Circuit breaker check: fail fast if provider is overloaded ---
        limiter = LLMRateLimiter.get_instance()
        if limiter.circuit_breaker.is_open:
            logger.warning(
                "PreScorer: Circuit breaker OPEN — falling back to FIFO for {} candidates.",
                len(candidates),
            )
            return candidates[:limit]

        logger.info(
            "PreScorer: Analizando {} candidatos para seleccionar Top {}...",
            len(candidates),
            limit,
        )

        # Construir prompt batch
        candidates_text = ""
        for idx, item in enumerate(candidates):
            title = item.get("title", "Sin título")
            summary = (item.get("summary") or "")[:200].replace(
                "\n", " "
            )  # Truncar resumen
            candidates_text += f"[{idx}] TITLE: {title} | SUMMARY: {summary}\n"

        prompt = (
            f"Here is a list of recent article candidates from source '{source_context}':\n\n"
            f"{candidates_text}\n\n"
            f"TASK: Identify the {limit} most scientifically significant, impactful, or intellectually engaging articles for a 'Scientific News' curation platform.\n"
            "Ignore generic updates, simple announcements, or minor news.\n"
            "Prioritize: Breakthroughs, Research, Deep Analysis, High Impact.\n\n"
            f"RESPONSE FORMAT: Return valid JSON containing ONLY a list of the integers corresponding to the top {limit} indices, ordered by relevance.\n"
            'Example: {"selected_indices": [3, 0, 7, 1, 4]}'
        )

        try:
            response = self.llm.generate_sync(
                prompt=prompt,
                json_mode=True,
                system="You are an expert Science Editor selecting the most important stories for publication. You output JSON only.",
            )

            selected_indices = []
            if isinstance(response, dict) and "selected_indices" in response:
                selected_indices = response["selected_indices"]
            elif isinstance(response, list):  # Fallback if LLM returns list directly
                selected_indices = response

            # Validar índices
            valid_indices = []
            for idx in selected_indices:
                if isinstance(idx, int) and 0 <= idx < len(candidates):  # noqa: SIM102
                    if idx not in valid_indices:
                        valid_indices.append(idx)

            # Si el LLM falló o devolvió menos, rellenar con los primeros (FIFO fallback)
            if len(valid_indices) < limit:
                logger.warning(
                    "PreScorer: LLM retornó {} válidos. Rellenando con FIFO.",
                    len(valid_indices),
                )
                for i in range(len(candidates)):
                    if len(valid_indices) >= limit:
                        break
                    if i not in valid_indices:
                        valid_indices.append(i)

            # Recortar si devolvió de más
            valid_indices = valid_indices[:limit]

            # Construir resultado
            selected_candidates = [candidates[i] for i in valid_indices]

            logger.info("PreScorer: Selección completada. Indices: {}", valid_indices)
            return selected_candidates

        except Exception as e:
            err_str = str(e)
            if "not configured" in err_str or "unavailable" in err_str.lower():
                logger.warning(
                    "PreScorer: LLM not available. Falling back to FIFO. ({})",
                    err_str,
                )
            elif (
                "circuit breaker" in err_str.lower() or "rate limit" in err_str.lower()
            ):
                logger.warning(
                    "PreScorer: Rate limited — falling back to FIFO. ({})",
                    err_str,
                )
            else:
                logger.error("Error en PreScorer: {}. Fallback a FIFO.", e)
            return candidates[:limit]
