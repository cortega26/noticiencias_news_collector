"""
Module role: Implements the AI Editorial Council for evaluating and improving news articles using an LLM provider.

Inputs:
- Article titles, summaries, and optional content snippets.

Outputs:
- CouncilResult dataclasses containing approval decisions, average scores, role-based scores, and feedback.
- Returns None if the external LLM provider fails.

Side effects:
- Issues synchronous text generation calls to the external or local LLM provider.

Invariants:
- Approval requires an average score >= 3.5, no individual score < 2.0, and explicit editor affirmation.
- Input article content exceeding 1500 characters is consistently truncated before evaluation.

Failure modes:
- Returns None and logs warnings if the LLM response is invalid, empty, or fails JSON parsing.
- Returns None and logs errors on general execution exceptions within the generation chain.
"""

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from news_collector.config.prompts import EDITORIAL_COUNCIL_SYSTEM_PROMPT
from news_collector.config.settings import CONFIG
from news_collector.infrastructure.llm.factory import get_provider
from news_collector.infrastructure.llm.model_registry import get_model_for_stage
from news_collector.utils.logger import get_logger

logger = get_logger().create_module_logger(__name__)


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

    def __init__(self, llm_client: Optional[Any] = None):
        if llm_client is None:
            model = get_model_for_stage("council", config=CONFIG, logger=logger)
            self.llm = get_provider(config=CONFIG, api_url=CONFIG.ollama.api_url, model=model)
        else:
            self.llm = llm_client

    def evaluate_article(
        self, title: str, summary: str, content: str = ""
    ) -> Optional[CouncilResult]:
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
                json_mode=True,
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

            if isinstance(response, dict):
                return self._parse_verdict(response)
            return None

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

        approved = average >= 3.5 and min_score >= 2.0 and is_editor_approved

        return CouncilResult(
            is_approved=approved,
            average_score=average,
            scores=scores_map,
            feedback=assessments,
            synthesis=data.get("editorial_synthesis", {}),
            raw_response=data,
        )
