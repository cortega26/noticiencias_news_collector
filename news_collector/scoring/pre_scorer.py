import json
import re
from typing import Any, Dict, List, Optional

from noticiencias.config_manager import load_config

from news_collector.infrastructure.llm.factory import get_provider
from news_collector.infrastructure.llm.model_registry import get_model_for_stage
from news_collector.infrastructure.llm.rate_limiter import LLMRateLimiter
from news_collector.scoring.latam_relevance import (
    rank_candidates_for_latam_audience,
    score_candidate_for_latam_audience,
)
from news_collector.utils.logger import get_logger

logger = get_logger().create_module_logger(__name__)

# IMPORTANT: Do not use %d or %s for string interpolation in logging calls here.
# This project uses Loguru, which requires `{}` formatting (e.g. logger.info("... {}", var)).
# Using %s or %d will result in literal '%d' printing in the logs and cause regressions.

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.IGNORECASE | re.DOTALL)


class PreScorer:
    """
    Evaluador preliminar que selecciona los mejores candidatos de un pool grande
    basándose en títulos y resúmenes antes de la extracción de texto completo.

    Rate-limit aware:
    - Checks the circuit breaker before attempting an LLM call.
    - Falls back to FIFO immediately when the breaker is open, avoiding
      wasted retries and blocking time.
    """

    def __init__(self, llm_client: Optional[Any] = None, config: Any | None = None):
        if llm_client is None:
            active_config = config or load_config()
            model = get_model_for_stage(
                "pre_scorer", config=active_config, logger=logger
            )
            self.llm = get_provider(
                config=active_config,
                api_url=active_config.ollama.api_url,
                model=model,
            )
        else:
            self.llm = llm_client
        self.model_name = self.llm.model

    @staticmethod
    def _extract_balanced_segment(  # noqa: C901
        text: str, open_char: str, close_char: str
    ) -> str | None:
        start_idx = text.find(open_char)
        if start_idx == -1:
            return None

        depth = 0
        in_string = False
        escape = False
        for idx, char in enumerate(text[start_idx:], start=start_idx):
            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    in_string = False
                continue

            if char == '"':
                in_string = True
                continue

            if char == open_char:
                depth += 1
            elif char == close_char:
                depth -= 1
                if depth == 0:
                    return text[start_idx : idx + 1]
        return None

    def _parse_selected_indices(self, response: Any) -> list[int]:  # noqa: C901
        if isinstance(response, dict):
            data = response.get("selected_indices", [])
            return data if isinstance(data, list) else []

        if isinstance(response, list):
            return response

        text = str(response or "").strip()
        if not text:
            return []

        candidates = [text]
        fenced_blocks = _JSON_FENCE_RE.findall(text)
        candidates.extend(block for block in fenced_blocks if block.strip())

        object_segment = self._extract_balanced_segment(text, "{", "}")
        if object_segment:
            candidates.append(object_segment)

        array_segment = self._extract_balanced_segment(text, "[", "]")
        if array_segment:
            candidates.append(array_segment)

        for candidate in candidates:
            try:
                parsed = json.loads(candidate)
            except json.JSONDecodeError:
                continue

            if isinstance(parsed, dict):
                data = parsed.get("selected_indices", [])
                if isinstance(data, list):
                    return data
            elif isinstance(parsed, list):
                return parsed

        return []

    @staticmethod
    def _score_candidate(candidate: Dict[str, Any]) -> float:
        return score_candidate_for_latam_audience(candidate)

    def _deterministic_rank_indices(
        self, candidates: List[Dict[str, Any]]
    ) -> list[int]:
        return rank_candidates_for_latam_audience(candidates)

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
            heuristic_rank = self._deterministic_rank_indices(candidates)
            logger.warning(
                "PreScorer: Circuit breaker OPEN — falling back to heuristic rank for {} candidates.",
                len(candidates),
            )
            return [candidates[i] for i in heuristic_rank[:limit]]

        logger.info(
            "PreScorer: Analizando {} candidatos para seleccionar Top {}...",
            len(candidates),
            limit,
        )
        heuristic_rank = self._deterministic_rank_indices(candidates)

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
            f"TASK: Identify the {limit} strongest stories for Noticiencias, a science-and-technology publication for Latin American readers.\n"
            "Prefer stories with either a direct Latin American connection OR strong universal relevance for a curious Spanish-speaking reader.\n"
            "Prioritize: breakthroughs, evidence-driven research, health, climate, AI, space, biodiversity, public-interest science, and consequential technology.\n"
            "Down-rank hyper-local campus administration, alumni updates, awards, fundraising, internal university announcements, and minor product/partnership news.\n\n"
            f"RESPONSE FORMAT: Return valid JSON containing ONLY a list of the integers corresponding to the top {limit} indices, ordered by relevance.\n"
            'Example: {"selected_indices": [3, 0, 7, 1, 4]}'
        )

        try:
            response = self.llm.generate_sync(
                prompt=prompt,
                system="You are an expert Science Editor selecting the most important stories for publication. You output JSON only.",
            )

            selected_indices = self._parse_selected_indices(response)

            # Validar índices
            valid_indices = []
            for idx in selected_indices:
                if isinstance(idx, int) and 0 <= idx < len(candidates):  # noqa: SIM102
                    if idx not in valid_indices:
                        valid_indices.append(idx)

            # Si el LLM falló o devolvió menos, rellenar con los primeros (FIFO fallback)
            if len(valid_indices) < limit:
                logger.warning(
                    "PreScorer: LLM retornó {} válidos. Rellenando con ranking heurístico editorial.",
                    len(valid_indices),
                )
                for i in heuristic_rank:
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
                    "PreScorer: LLM not available. Falling back to heuristic rank. ({})",
                    err_str,
                )
            elif (
                "circuit breaker" in err_str.lower() or "rate limit" in err_str.lower()
            ):
                logger.warning(
                    "PreScorer: Rate limited — falling back to heuristic rank. ({})",
                    err_str,
                )
            else:
                logger.error("Error en PreScorer: {}. Fallback a heuristic rank.", e)
            return [candidates[i] for i in heuristic_rank[:limit]]
