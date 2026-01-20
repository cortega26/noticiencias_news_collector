import logging
import json
from typing import List, Dict, Any, Optional

from news_collector.infrastructure.llm.provider import OllamaProvider

logger = logging.getLogger(__name__)

class PreScorer:
    """
    Evaluador preliminar que selecciona los mejores candidatos de un pool grande
    basándose en títulos y resúmenes antes de la extracción de texto completo.
    """

    def __init__(self, llm_client: Optional[OllamaProvider] = None):
        self.llm = llm_client or OllamaProvider()
        self.model_name = self.llm.model

    def select_top_candidates(
        self, 
        candidates: List[Dict[str, Any]], 
        limit: int = 5,
        source_context: str = ""
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
            logger.info(f"PreScorer: Solicitados {limit}, disponibles {len(candidates)}. Retornando todos.")
            return candidates

        logger.info(f"🤖 PreScorer: Analizando {len(candidates)} candidatos para seleccionar Top {limit}...")

        # Construir prompt batch
        candidates_text = ""
        for idx, item in enumerate(candidates):
            title = item.get("title", "Sin título")
            summary = (item.get("summary") or "")[:200].replace("\n", " ") # Truncar resumen
            candidates_text += f"[{idx}] TITLE: {title} | SUMMARY: {summary}\n"

        prompt = (
            f"Here is a list of recent article candidates from source '{source_context}':\n\n"
            f"{candidates_text}\n\n"
            f"TASK: Identify the {limit} most scientifically significant, impactful, or intellectually engaging articles for a 'Scientific News' curation platform.\n"
            "Ignore generic updates, simple announcements, or minor news.\n"
            "Prioritize: Breakthroughs, Research, Deep Analysis, High Impact.\n\n"
            f"RESPONSE FORMAT: Return valid JSON containing ONLY a list of the integers corresponding to the top {limit} indices, ordered by relevance.\n"
            "Example: {\"selected_indices\": [3, 0, 7, 1, 4]}"
        )

        try:
            response = self.llm.generate_sync(
                prompt=prompt, 
                json_mode=True,
                system="You are an expert Science Editor selecting the most important stories for publication. You output JSON only."
            )

            selected_indices = []
            if isinstance(response, dict) and "selected_indices" in response:
                selected_indices = response["selected_indices"]
            elif isinstance(response, list): # Fallback if LLM returns list directly
                selected_indices = response

            # Validar índices
            valid_indices = []
            for idx in selected_indices:
                if isinstance(idx, int) and 0 <= idx < len(candidates):
                    if idx not in valid_indices:
                        valid_indices.append(idx)
            
            # Si el LLM falló o devolvió menos, rellenar con los primeros (FIFO fallback)
            if len(valid_indices) < limit:
                logger.warning(f"PreScorer: LLM retornó {len(valid_indices)} válidos. Rellenando con FIFO.")
                for i in range(len(candidates)):
                    if len(valid_indices) >= limit:
                        break
                    if i not in valid_indices:
                        valid_indices.append(i)
            
            # Recortar si devolvió de más
            valid_indices = valid_indices[:limit]

            # Construir resultado
            selected_candidates = [candidates[i] for i in valid_indices]
            
            logger.info(f"✅ PreScorer: Selección completada. Indices: {valid_indices}")
            return selected_candidates

        except Exception as e:
            logger.error(f"Error en PreScorer: {e}. Fallback a FIFO.")
            return candidates[:limit]
