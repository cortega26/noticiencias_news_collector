"""
Editorial Council Module
========================

Implements the AI Editorial Council for evaluating and improving news articles.
"""

import json
import logging
from typing import Any, Dict, Optional, List
from dataclasses import dataclass

from news_collector.infrastructure.llm.provider import OllamaProvider
from news_collector.config.prompts import EDITORIAL_COUNCIL_SYSTEM_PROMPT

logger = logging.getLogger(__name__)

@dataclass
class CouncilResult:
    is_approved: bool
    average_score: float
    scores: Dict[str, float]
    feedback: List[Dict[str, Any]]
    synthesis: Dict[str, str]
    raw_response: Dict[str, Any]

class EditorialCouncil:
    """
    Agente que coordina la evaluación de artículos por el Consejo Editorial IA.
    """

    def __init__(self, llm_client: Optional[OllamaProvider] = None):
        self.llm = llm_client or OllamaProvider()

    def evaluate_article(self, title: str, summary: str, content: str = "") -> Optional[CouncilResult]:
        """
        Envía un artículo al consejo para su evaluación.

        Args:
            title: Titular actual
            summary: Resumen del artículo
            content: Contenido completo (opcional, se trunca si es muy largo)

        Returns:
            CouncilResult con la decisión y feedback, o None si falla el LLM.
        """
        
        # Prepare input for the prompt
        article_text = f"TITULAR: {title}\n\nRESUMEN: {summary}\n\n"
        if content:
            # Provide first 1500 chars of content for context
            article_text += f"FRAGMENTO CONTENIDO: {content[:1500]}..."

        try:
            response = self.llm.generate_sync(
                prompt=article_text,
                system=EDITORIAL_COUNCIL_SYSTEM_PROMPT,
                json_mode=True
            )

            if not response or "error" in response:
                logger.warning(f"Editorial Council failed: {response}")
                return None

            if isinstance(response, str):
                # Should have been parsed by llm.generate if format=json, but just in case
                try:
                    response = json.loads(response)
                except json.JSONDecodeError:
                    logger.error("Failed to parse Council response as JSON")
                    return None

            return self._parse_verdict(response)

        except Exception as e:
            logger.error(f"Error in Editorial Council execution: {e}")
            return None

    def _parse_verdict(self, data: Dict[str, Any]) -> CouncilResult:
        """Applies the Publication Rules to the JSON response."""
        
        assessments = data.get("council_assessments", [])
        
        total_score = 0.0
        scores_map = {}
        min_score = 5.0
        
        for item in assessments:
            role = item.get("role", "Unknown")
            score = float(item.get("score", 0))
            scores_map[role] = score
            total_score += score
            if score < min_score:
                min_score = score
        
        count = len(assessments) or 1
        average = total_score / count
        
        editor_approval = data.get("editor_approval", "").lower()
        is_editor_approved = "sí" in editor_approval or "si" in editor_approval
        
        # Rule of Publication
        # - Promedio >= 3.5
        # - Ningún rol puntúa < 2
        # - Editor responde explícitamente "Sí..."
        
        approved = (
            average >= 3.5 and
            min_score >= 2.0 and
            is_editor_approved
        )
        
        return CouncilResult(
            is_approved=approved,
            average_score=average,
            scores=scores_map,
            feedback=assessments,
            synthesis=data.get("editorial_synthesis", {}),
            raw_response=data
        )
