import logging
import json
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

from news_collector.storage.models import Article
from news_collector.utils.llm_client import LLMClient
from .basic_scorer import BasicScorer

logger = logging.getLogger(__name__)

class CognitiveScorer(BasicScorer):
    """
    Scorer avanzado que utiliza IA para evaluar el 'Engagement Cognitivo'.
    Extiende BasicScorer para reutilizar métricas base (Fuente, Recencia, Calidad)
    y combina con análisis semántico profundo.
    """
    
    def __init__(self, weights: Optional[Dict[str, float]] = None, llm_client: LLMClient = None):
        print("DEBUG: CognitiveScorer INITIALIZED")
        # Default weights if none provided (Prompt Maestro formula)
        default_weights = {
            "source_credibility": 0.20,
            "recency": 0.20,
            "content_quality": 0.20,
            "cognitive_engagement": 0.40
        }
        
        # If weights are provided (e.g. from UI/Config), we use them.
        # We need to ensure 'engagement_potential' from standard config maps to 'cognitive_engagement' 
        # if the latter is missing.
        final_weights = weights.copy() if weights else default_weights
        
        if "engagement_potential" in final_weights and "cognitive_engagement" not in final_weights:
            final_weights["cognitive_engagement"] = final_weights.pop("engagement_potential")
            
        super().__init__(weights=final_weights)
        self.llm = llm_client or LLMClient()
        self.version = "2.0-cognitive"

    def score_article(
        self, article: Article, source_config: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        Calcula el score usando el algoritmo 'Prompt Maestro'.
        """
        print(f"DEBUG: CognitiveScorer.score_article called for {article.title}")
        try:
            # 1. Métricas Base (Reutilizadas de BasicScorer, retornan 0-1)
            source_score = self._calculate_source_credibility_score(article, source_config)
            recency_score = self._calculate_recency_score(article)
            content_score = self._calculate_content_quality_score(article)
            
            # 2. Cognitive Engagement (Calculado vía LLM, retorna 0-5, normalizamos a 0-1)
            cognitive_result = self._calculate_cognitive_engagement(article)
            cognitive_raw = cognitive_result.get("score", 0.0) # 0-5
            cognitive_score = min(1.0, cognitive_raw / 5.0) # Normalizado 0-1
            
            # 3. Cálculo Final
            # FinalScore = 0.2*Source + 0.2*Recency + 0.2*Quality + 0.4*Cognitive
            final_score = (
                source_score * self.weights["source_credibility"] +
                recency_score * self.weights["recency"] +
                content_score * self.weights["content_quality"] +
                cognitive_score * self.weights["cognitive_engagement"]
            )
             
            final_score = max(0.0, min(1.0, final_score))
            
            # 4. Decisión Editorial
            # < 0.60 Descartar, 0.60-0.74 Publicable, >= 0.75 Prioridad
            decision = "discard"
            if final_score >= 0.75:
                decision = "priority"
            elif final_score >= 0.60:
                decision = "publishable"
                
            should_include = final_score >= 0.60
            
            result = {
                "final_score": round(final_score, 4),
                "should_include": should_include,
                "decision_label": decision,
                "components": {
                    "source_credibility": round(source_score, 4),
                    "recency": round(recency_score, 4),
                    "content_quality": round(content_score, 4),
                    "cognitive_engagement_norm": round(cognitive_score, 4),
                    "cognitive_engagement_raw": round(cognitive_raw, 2),
                    # Required by ScoringRequestModel contract
                    "engagement": round(cognitive_score, 4),
                },
                "cognitive_details": cognitive_result.get("details", {}),
                "weights": self.weights.copy(),
                "explanation": self._generate_cognitive_explanation(
                    article, final_score, source_score, recency_score, content_score, cognitive_score, cognitive_result
                ),
                "version": self.version,
                "calculated_at": datetime.now(timezone.utc).isoformat(),
            }
            
            logger.info(f"🧠 Cognitive Score: {final_score:.3f} ({decision}) - {article.title[:40]}...")
            return result
            
        except Exception as e:
            logger.error(f"Error en CognitiveScorer para {article.id}: {e}", exc_info=True)
            # Fallback a implementación base via instancia limpia
            weights = {
                "source_credibility": 0.25,
                "recency": 0.20,
                "content_quality": 0.25,
                "engagement_potential": 0.30,
            }
            from .basic_scorer import BasicScorer
            fallback_scorer = BasicScorer(weights)
            return fallback_scorer.score_article(article, source_config)

    def _calculate_cognitive_engagement(self, article: Article) -> Dict[str, Any]:
        """
        Consulta al LLM para evaluar las 5 dimensiones del Engagement Cognitivo.
        """
        text_content = f"Title: {article.title}\n\nSummary: {article.summary}\n\nContent Fragment: {(article.content or '')[:1000]}"
        print(f"DEBUG: sending to LLM (len={len(text_content)}): {text_content[:50]}...")
        
        system_prompt = (
            "Eres el motor de evaluación cognitiva de Noticiencias. "
            "Tu objetivo no es maximizar clics, sino identificar noticias con mayor potencial de impacto intelectual.\n"
            "Analiza el siguiente artículo y puntúa de 0 a 5 los siguientes sub-ejes:\n"
            "1. Contraintuitivo: ¿Qué creencia común queda invalidada o tensionada?\n"
            "2. ImpactoHumano: ¿Afecta decisiones reales del lector promedio?\n"
            "3. ConflictoIdeas: ¿Enfrenta paradigmas, modelos o teorías?\n"
            "4. Incertidumbre: ¿Qué aspecto relevante aún no se entiende?\n"
            "5. UtilidadPractica: ¿Cambia comportamiento o mentalidad mañana?\n"
            "\n"
            "Retorna SOLO un JSON con este formato:\n"
            "{\n"
            '  "scores": {\n'
            '    "contraintuitivo": 0-5,\n'
            '    "impacto_humano": 0-5,\n'
            '    "conflicto_ideas": 0-5,\n'
            '    "incertidumbre": 0-5,\n'
            '    "utilidad_practica": 0-5\n'
            "  },\n"
            '  "reasoning": "Breve justificación de 1 linea"\n'
            "}"
        )
        
        response = self.llm.generate(prompt=text_content, system=system_prompt, format="json")
        
        if isinstance(response, dict) and "scores" in response:
            scores = response["scores"]
            # Calcular promedio 0-5
            # CognitiveEngagement = 0.20 * sum(sub-ejes)
            # Equivalente a promedio simple si hay 5 ejes.
            values = [
                float(scores.get("contraintuitivo", 0)),
                float(scores.get("impacto_humano", 0)),
                float(scores.get("conflicto_ideas", 0)),
                float(scores.get("incertidumbre", 0)),
                float(scores.get("utilidad_practica", 0)),
            ]
            raw_average = sum(values) / 5.0 * 5.0 # Espera, la formula es 0.20 * sum.
            # Si suma es 25, 0.2 * 25 = 5.
            # Sí, es la suma multiplicada por 0.2, que es matemáticamente el promedio si se divide por 1 (no, 0.2 = 1/5).
            # Entonces es simplemente el promedio de los 5 valores.
            raw_score = sum(values) * 0.20
            
            return {
                "score": raw_score, # 0-5 scale
                "details": scores,
                "reasoning": response.get("reasoning", "")
            }
        
        logger.warning(f"Respuesta LLM inválida: {response}")
        return {"score": 0.0, "details": {}, "reasoning": "Error en LLM"}

    def _generate_cognitive_explanation(
        self, article, final, source, recency, content, cognitive_norm, cognitive_details
    ):
        # Reimplementación completa para soportar la estructura cognitiva
        explanation = {
            "overall_assessment": self._get_overall_assessment(final),
            "component_breakdown": {
                "source_credibility": {
                    "score": source,
                    "weight": self.weights["source_credibility"],
                    "contribution": source * self.weights["source_credibility"],
                    "factors": self._explain_source_score(article),
                },
                "recency": {
                    "score": recency,
                    "weight": self.weights["recency"],
                    "contribution": recency * self.weights["recency"],
                    "factors": self._explain_recency_score(article),
                },
                "content_quality": {
                    "score": content,
                    "weight": self.weights["content_quality"],
                    "contribution": content * self.weights["content_quality"],
                    "factors": self._explain_content_score(article),
                },
                "cognitive_engagement": {
                    "score": cognitive_norm,
                    "weight": self.weights["cognitive_engagement"],
                    "contribution": cognitive_norm * self.weights["cognitive_engagement"],
                    "factors": ["Evaluación por IA", f"Reasoning: {cognitive_details.get('reasoning', '')}"],
                    "details": cognitive_details
                },
            },
            # Simplified lists for now as the parent helpers methods need args I might not have handy or they work ok
            "key_strengths": [], 
            "improvement_areas": [],
            "recommendation": (
                "priority" if final >= 0.75 else "publishable" if final >= 0.60 else "discard"
            ),
        }
        return explanation
