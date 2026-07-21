# src/scoring/basic_scorer.py
# Sistema de scoring inteligente para News Collector
# ================================================

"""
Module role: Evaluates articles across multiple dimensions (credibility, recency, quality, engagement) to compute a final importance score.

Inputs:
- `Article` representations (ORM models or mocked objects containing content, metadata, and dates).
- Component weights and source configurations optionally provided to override defaults.

Outputs:
- A strictly validated scoring dictionary containing `final_score`, `should_include`, `components` breakdown, and a detailed human-readable `explanation`.

Side effects:
- None. (Uses a thread executor for async translation but performs no external IO).

Invariants:
- The output payload strictly conforms to the `ScoringRequestModel` contract.
- Component weights are aggressively normalized if they do not sum to 1.0.
- Final calculated scores are strictly clamped to the [0.0, 1.0] range.

Failure modes:
- Calculation exceptions are caught and explicitly result in a fallback safe payload (score 0.0, `should_include=False`, and an error explanation).
- Validation errors during Pydantic schema enforcement raise a `ValueError` indicating a critical scoring failure.
"""

import asyncio
import math
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, cast

from pydantic import ValidationError

from news_collector.config.settings import get_runtime_config
from news_collector.contracts import ScoringRequestModel
from news_collector.utils.dict_wrapper import SafeNamespace
from news_collector.utils.logger import get_logger

from ..storage.models import Article
from .interfaces import AsyncScorer

logger = get_logger().create_module_logger(__name__)


class BasicScorer(AsyncScorer):
    """
    Sistema de scoring multidimensional para artículos científicos.

    Este scorer evalúa artículos en cuatro dimensiones principales:
    1. Credibilidad de la fuente (¿podemos confiar en esta información?)
    2. Recencia (¿qué tan actual es?)
    3. Calidad del contenido (¿está bien escrito y es sustantivo?)
    4. Potencial de engagement (¿va a interesar a la audiencia?)

    Cada dimensión contribuye al score final según pesos configurables,
    permitiendo ajustar el balance según las necesidades del momento.
    """

    def __init__(self, weights: Optional[Dict[str, float]] = None):
        """
        Inicializa el scorer con pesos específicos.

        Args:
            weights: Diccionario con pesos para cada dimensión.
                    Si no se proporciona, usa los valores de configuración.
        """
        self.weights = weights or get_runtime_config().scoring_config["weights"].copy()
        self.version = "1.0"

        # Validar que los pesos sumen 1.0
        weight_sum = sum(self.weights.values())
        if abs(weight_sum - 1.0) > 0.01:
            logger.warning(
                f"Los pesos no suman 1.0 (suma: {weight_sum}). Normalizando..."
            )
            for key in self.weights:
                self.weights[key] /= weight_sum

        # Cache para optimizar cálculos repetitivos
        self._keyword_cache: Dict[str, float] = {}

        logger.info(f"🧠 Scorer inicializado con pesos: {self.weights}")

    def score_article(
        self, article: Article, source_config: Dict[str, Any] | None = None
    ) -> Dict[str, Any]:
        """
        Calcula el score completo de un artículo.

        Esta función es como tener un comité de evaluación que analiza
        cada artículo desde múltiples perspectivas y llega a una decisión
        fundamentada y explicable.

        Args:
            article: El artículo a evaluar
            source_config: Configuración de la fuente (opcional)

        Returns:
            Diccionario con score final y desglose completo
        """
        try:
            # Calcular cada componente del score
            source_score = self._calculate_source_credibility_score(
                article, source_config
            )
            recency_score = self._calculate_recency_score(article)
            content_score = self._calculate_content_quality_score(article)
            engagement_score = self._calculate_engagement_potential_score(article)

            # Calcular score final ponderado
            final_score = (
                source_score * self.weights["source_credibility"]
                + recency_score * self.weights["recency"]
                + content_score * self.weights["content_quality"]
                + engagement_score * self.weights["engagement_potential"]
            )

            # Asegurar que esté en rango [0, 1]
            final_score = max(0.0, min(1.0, final_score))

            # Crear explicación detallada
            explanation = self._generate_score_explanation(
                article,
                final_score,
                source_score,
                recency_score,
                content_score,
                engagement_score,
            )

            # Determinar si el artículo debe ser incluido
            should_include = (
                final_score >= get_runtime_config().scoring_config["minimum_score"]
            )

            result = {
                "final_score": round(final_score, 4),
                "should_include": should_include,
                "components": {
                    "source_credibility": round(source_score, 4),
                    "recency": round(recency_score, 4),
                    "content_quality": round(content_score, 4),
                    "engagement_potential": round(engagement_score, 4),
                },
                "weights": self.weights.copy(),
                "explanation": explanation,
                "version": self.version,
                "calculated_at": datetime.now(timezone.utc).isoformat(),
            }

            logger.debug(
                f"📊 Artículo scored: {final_score:.3f} - {article.title[:50]}..."
            )

            try:
                validated = ScoringRequestModel.model_validate(result)
            except ValidationError as exc:
                identifier = getattr(article, "id", getattr(article, "url", "unknown"))
                raise ValueError(
                    f"Invalid scoring payload for article {identifier}: {exc}"
                ) from exc

            return validated.model_dump()

        except Exception as e:
            logger.error(f"Error calculando score para artículo {article.id}: {e}")
            print(
                f"CRITICAL SCORING ERROR for {getattr(article, 'id', 'unknown')}: {e}"
            )
            import traceback

            traceback.print_exc()
            fallback = {
                "final_score": 0.0,
                "should_include": False,
                "components": {
                    "source_credibility": 0.0,
                    "recency": 0.0,
                    "content_quality": 0.0,
                    "engagement": 0.0,
                },
                "weights": self.weights.copy(),
                "explanation": {"error": f"Error en cálculo: {str(e)}"},
                "version": self.version,
                "calculated_at": datetime.now(timezone.utc).isoformat(),
            }
            try:
                return ScoringRequestModel.model_validate(fallback).model_dump()
            except ValidationError:
                return fallback

    async def score_article_async(self, article_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Score an article asynchronously using a thread executor.

        Args:
            article_data: Dictionary containing 'article' data and optional 'source_config'.

        Returns:
            Dictionary with scoring results.
        """
        # Extract article data and config
        article_dict = article_data.get("article", article_data)
        source_config_obj = article_data.get("source_config")
        source_config = (
            source_config_obj if isinstance(source_config_obj, dict) else None
        )

        # Parse date strings to datetime objects if necessary
        for date_field in ["published_date", "collected_date"]:
            val = article_dict.get(date_field)
            if isinstance(val, str):
                try:  # noqa: SIM105
                    article_dict[date_field] = datetime.fromisoformat(
                        val.replace("Z", "+00:00")
                    )
                except (ValueError, TypeError):
                    pass

        # Create a lightweight object to mimic Article interface for existing methods
        # This allows reusing all the private calculation methods without modification
        article_obj = SafeNamespace(**article_dict)

        # Explicitly ensure 'collected_date' exists as datetime
        if not article_obj.collected_date:
            article_obj.collected_date = datetime.now(timezone.utc)  # type: ignore[attr-defined]

        # Ensure 'article_metadata' exists if it's missing (SafeNamespace returns None, causing problems)
        if article_obj.article_metadata is None:
            article_obj.article_metadata = {}  # type: ignore[attr-defined]

        # Run the synchronous scoring logic in a separate thread to avoid blocking the event loop
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            self.score_article,
            cast(Article, article_obj),
            source_config,  # Use default executor
        )

        return result

    def _calculate_source_credibility_score(
        self, article: Article, source_config: Dict[str, Any] | None = None
    ) -> float:
        """
        Evalúa la credibilidad del artículo basado en sus propios méritos (peer-review, DOI, journal).
        La credibilidad base de la fuente es ignorada para evaluar las noticias en sus propios méritos.

        Factores considerados:
        - Credibilidad base neutral (0.5)
        - Si es peer-reviewed vs preprint
        - Reputación del journal
        - Presencia de DOI
        """
        score = 0.0

        # La credibilidad base es fija (neutral) para evaluar noticias por sus propios méritos
        base_credibility = 0.5

        score += base_credibility * 0.6  # 60% del score base viene del baseline neutral

        # Bonus por peer review
        if article.peer_reviewed:
            score += 0.2
        elif article.is_preprint:
            score += 0.1  # Preprints tienen algún valor pero menos

        # Bonus por presencia de DOI (indica formalidad académica)
        if article.doi:
            score += 0.1

        # Bonus por journal reconocido
        if article.journal:
            journal_bonus = self._evaluate_journal_reputation(article.journal)
            score += journal_bonus * 0.1

        return min(1.0, score)

    def _calculate_recency_score(self, article: Article) -> float:
        """
        Evalúa qué tan reciente es el artículo.

        Este método es como tener un editor de noticias que entiende que
        la información más reciente generalmente es más valiosa, pero
        que la importancia de la recencia varía según el tipo de contenido.

        La función de decay es logarítmica: las primeras horas/días son
        cruciales, pero después la pérdida de valor es más gradual.
        """
        if not article.published_date:
            # Si no hay fecha, usar fecha de recolección con penalización
            reference_date = article.collected_date
            penalty = 0.8  # 20% de penalización por fecha desconocida
        else:
            reference_date = article.published_date
            penalty = 1.0

        # Ensure reference_date is timezone-aware and normalized to UTC
        if reference_date.tzinfo is None:
            reference_date = reference_date.replace(tzinfo=timezone.utc)
        else:
            reference_date = reference_date.astimezone(timezone.utc)

        try:
            # Calcular edad en horas
            now = datetime.now(timezone.utc)
            # Both dates are now UTC-aware, subtraction is safe
            age_hours = (now - reference_date).total_seconds() / 3600
        except Exception as e:
            # Should hopefully not happen now, but log just in case
            logger.error(
                f"Error calculating recency: {e}. Ref: {reference_date}, Now: {now}"
            )
            # Fallback safe value
            age_hours = 24 * 7  # Assume 1 week old on error

        # Función de decay logarítmica
        # Score alto para las primeras 24 horas, decay gradual después
        if age_hours <= 1:
            score = 1.0  # Máximo score para la primera hora
        elif age_hours <= 24:
            # Decay suave en las primeras 24 horas
            score = 0.9 + 0.1 * math.exp(-(age_hours - 1) / 8)
        elif age_hours <= 168:  # Una semana
            # Decay más pronunciado después del primer día
            score = 0.7 * math.exp(-(age_hours - 24) / 48)
        else:
            # Después de una semana, score mínimo pero no cero
            score = 0.1 * math.exp(-(age_hours - 168) / 336)

        return max(0.05, min(1.0, score * penalty))  # Mínimo 5%, máximo 100%

    def _calculate_content_quality_score(self, article: Article) -> float:
        """
        Evalúa la calidad del contenido del artículo.

        Este método es como tener un editor experto que puede evaluar
        rápidamente si un texto está bien escrito, es sustantivo,
        y proporciona información valiosa.
        """
        score = 0.5  # Score base neutral

        # Evaluar longitud del contenido
        content_length_score = self._evaluate_content_length(article)
        score += content_length_score * 0.2

        # Evaluar calidad del título
        title_score = self._evaluate_title_quality(article.title)
        score += title_score * 0.3

        # Evaluar calidad del resumen/contenido
        content_score = self._evaluate_text_quality(article.summary or "")
        score += content_score * 0.3

        # Evaluar presencia de keywords científicos importantes
        keyword_score = self._evaluate_scientific_keywords(article)
        score += keyword_score * 0.2

        return max(0.0, min(1.0, score))

    def _calculate_engagement_potential_score(self, article: Article) -> float:
        """
        Predice el potencial de engagement del artículo.

        Este método es como tener un experto en redes sociales que puede
        predecir qué contenido va a resonar con la audiencia basándose
        en patrones históricos y características del contenido.
        """
        score = 0.5  # Score base

        # Evaluar "shareabilidad" del título
        title_engagement = self._evaluate_title_engagement_potential(article.title)
        score += title_engagement * 0.4

        # Evaluar temas trending
        trending_score = self._evaluate_trending_topics(article)
        score += trending_score * 0.3

        # Evaluar claridad para audiencia general
        accessibility_score = self._evaluate_accessibility(article)
        score += accessibility_score * 0.2

        # Evaluar "wow factor" - palabras que indican descubrimientos importantes
        wow_factor = self._evaluate_wow_factor(article)
        score += wow_factor * 0.1

        return max(0.0, min(1.0, score))

    # Métodos auxiliares para evaluaciones específicas
    # ===============================================

    @staticmethod
    def _as_text(value: object | None) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        return str(value)

    def _evaluate_journal_reputation(self, journal_name: object | None) -> float:
        """
        Evalúa la reputación de un journal científico.

        Este método usa una lista curada de journals prestigiosos.
        En una versión más avanzada, podríamos conectar con APIs
        de impact factors reales.
        """
        journal_text = self._as_text(journal_name)
        if not journal_text:
            return 0.0

        journal_lower = journal_text.lower()

        # Journals de élite (impact factor > 30)
        elite_journals = [
            "nature",
            "science",
            "cell",
            "new england journal of medicine",
            "lancet",
            "nejm",
            "pnas",
            "nature medicine",
            "nature genetics",
        ]

        # Journals de alta calidad (impact factor 10-30)
        high_quality = [
            "plos one",
            "scientific reports",
            "nature communications",
            "journal of clinical investigation",
            "immunity",
            "neuron",
        ]

        # Journals respetables (impact factor 5-10)
        respectable = [
            "journal of biological chemistry",
            "molecular cell",
            "cancer research",
            "blood",
            "diabetes",
        ]

        for elite in elite_journals:
            if elite in journal_lower:
                return 1.0

        for high in high_quality:
            if high in journal_lower:
                return 0.8

        for resp in respectable:
            if resp in journal_lower:
                return 0.6

        # Si tiene "journal" en el nombre, probablemente es legítimo
        if "journal" in journal_lower:
            return 0.4

        return 0.2  # Score mínimo para journals desconocidos

    def _evaluate_content_length(self, article: Article) -> float:
        """
        Evalúa si el artículo tiene una longitud apropiada.

        Ni muy corto (falta sustancia) ni muy largo (difícil de consumir).
        """
        total_length = len((article.title or "") + " " + (article.summary or ""))

        if total_length < 100:
            return 0.2  # Muy corto
        elif total_length < 300:
            return 0.6  # Un poco corto
        elif total_length < 800:
            return 1.0  # Longitud ideal
        elif total_length < 1500:
            return 0.8  # Un poco largo
        else:
            return 0.5  # Muy largo

    def _evaluate_title_quality(self, title: object | None) -> float:
        """
        Evalúa la calidad del título del artículo.

        Un buen título científico debe ser descriptivo, específico,
        y libre de clickbait.
        """
        title_text = self._as_text(title)
        if not title_text:
            return 0.0

        score = 0.5
        title_lower = title_text.lower()

        # Penalizar clickbait
        clickbait_indicators = [
            "you won't believe",
            "shocking",
            "amazing",
            "incredible",
            "doctors hate",
            "secret",
            "miracle",
        ]

        for indicator in clickbait_indicators:
            if indicator in title_lower:
                score -= 0.3

        # Bonificar indicadores de calidad científica
        quality_indicators = [
            "study",
            "research",
            "analysis",
            "discovery",
            "investigation",
            "clinical trial",
            "peer-reviewed",
            "published",
        ]

        for indicator in quality_indicators:
            if indicator in title_lower:
                score += 0.1

        # Bonificar especificidad (números, nombres de instituciones)
        if re.search(r"\d+", title_text):  # Contiene números
            score += 0.1

        if re.search(r"university|institute|lab", title_lower):  # Instituciones
            score += 0.1

        # Penalizar títulos muy cortos o muy largos
        if len(title_text) < 30:
            score -= 0.2
        elif len(title_text) > 150:
            score -= 0.1

        return max(0.0, min(1.0, score))

    def _evaluate_text_quality(self, text: object | None) -> float:
        """
        Evalúa la calidad general del texto.

        Considera factores como diversidad de vocabulario,
        estructura de oraciones, y presencia de información técnica.
        """
        text_value = self._as_text(text)
        if not text_value or len(text_value) < 50:
            return 0.0

        score = 0.5

        # Evaluar diversidad de vocabulario
        words = re.findall(r"\w+", text_value.lower())
        if len(words) > 0:
            unique_words = len(set(words))
            diversity = unique_words / len(words)
            score += min(0.3, diversity * 0.6)  # Máximo 0.3 por diversidad

        # Bonificar presencia de terminología técnica/científica
        technical_terms = [
            "molecule",
            "protein",
            "gene",
            "cell",
            "tissue",
            "organism",
            "hypothesis",
            "methodology",
            "statistical",
            "significant",
            "correlation",
            "analysis",
            "experiment",
            "treatment",
        ]

        technical_count = sum(
            1 for term in technical_terms if term in text_value.lower()
        )
        score += min(0.2, technical_count * 0.05)  # Máximo 0.2 por términos técnicos

        return max(0.0, min(1.0, score))

    def _evaluate_scientific_keywords(self, article: Article) -> float:
        """
        Evalúa la presencia de keywords científicos importantes.

        Busca palabras que indican que el contenido es científicamente relevante.
        """
        # Combinar título y resumen para análisis
        full_text = f"{article.title or ''} {article.summary or ''}".lower()

        # Keywords que aumentan la relevancia
        boost_keywords = get_runtime_config().text_processing_config["boost_keywords"]

        # Contar keywords encontrados
        found_keywords = sum(
            1 for keyword in boost_keywords if keyword.lower() in full_text
        )

        # Normalizar score (máximo si tiene 5+ keywords relevantes)
        score = min(1.0, found_keywords / 5.0)

        return score

    def _evaluate_title_engagement_potential(self, title: object | None) -> float:
        """
        Evalúa el potencial de engagement del título.

        Busca elementos que hacen títulos más compartibles en redes sociales.
        """
        title_text = self._as_text(title)
        if not title_text:
            return 0.0

        score = 0.5
        title_lower = title_text.lower()

        # Palabras que aumentan engagement
        engaging_words = [
            "breakthrough",
            "discovery",
            "first",
            "new",
            "revolutionary",
            "surprising",
            "unexpected",
            "major",
            "significant",
            "important",
        ]

        for word in engaging_words:
            if word in title_lower:
                score += 0.1

        # Números específicos tienden a ser más engaging
        if re.search(r"\d+%|\d+ times|\d+ years", title_text):
            score += 0.1

        # Preguntas pueden ser engaging
        if "?" in title_text:
            score += 0.05

        return max(0.0, min(1.0, score))

    def _evaluate_trending_topics(self, article: Article) -> float:
        """
        Evalúa si el artículo trata temas que están trending.

        Esta es una versión simplificada. En producción, esto se conectaría
        con APIs de Google Trends, análisis de redes sociales, etc.
        """
        full_text = f"{article.title or ''} {article.summary or ''}".lower()

        # Temas que están "hot" en ciencia actualmente
        trending_topics = [
            "artificial intelligence",
            "ai",
            "machine learning",
            "chatgpt",
            "climate change",
            "carbon",
            "renewable energy",
            "covid",
            "vaccine",
            "pandemic",
            "virus",
            "quantum",
            "crispr",
            "gene editing",
            "space",
            "mars",
            "webb telescope",
            "black hole",
        ]

        found_topics = sum(1 for topic in trending_topics if topic in full_text)

        # Normalizar (máximo si tiene 3+ temas trending)
        score = min(1.0, found_topics / 3.0)

        return score

    def _evaluate_accessibility(self, article: Article) -> float:
        """
        Evalúa qué tan accesible es el artículo para audiencia general.

        Contenido muy técnico puede ser importante pero menos "shareable".
        """
        full_text = f"{article.title or ''} {article.summary or ''}".lower()

        # Palabras muy técnicas que pueden alienar audiencia general
        technical_jargon = [
            "methodology",
            "statistical significance",
            "p-value",
            "multivariate analysis",
            "phenotype",
            "genotype",
            "chromatography",
            "spectroscopy",
            "phylogenetic",
        ]

        jargon_count = sum(1 for term in technical_jargon if term in full_text)

        # Penalizar exceso de jargón
        accessibility_score = max(0.3, 1.0 - (jargon_count * 0.1))

        return accessibility_score

    def _evaluate_wow_factor(self, article: Article) -> float:
        """
        Evalúa el "factor wow" del artículo.

        Busca indicadores de que esto es algo realmente especial
        que va a sorprender a la gente.
        """
        full_text = f"{article.title or ''} {article.summary or ''}".lower()

        wow_indicators = [
            "first time",
            "never before",
            "unprecedented",
            "record",
            "largest",
            "smallest",
            "fastest",
            "slowest",
            "breakthrough",
            "revolutionary",
            "game-changing",
            "nobel",
            "award-winning",
            "world-class",
        ]

        wow_count = sum(1 for indicator in wow_indicators if indicator in full_text)

        # Normalizar (máximo si tiene 2+ indicadores wow)
        score = min(1.0, wow_count / 2.0)

        return score

    def _generate_score_explanation(
        self,
        article: Article,
        final_score: float,
        source_score: float,
        recency_score: float,
        content_score: float,
        engagement_score: float,
    ) -> Dict[str, Any]:
        """
        Genera una explicación detallada del score.

        Esta explicación es crucial para transparencia y para permitir
        mejoras futuras del algoritmo.
        """
        explanation = {
            "overall_assessment": self._get_overall_assessment(final_score),
            "component_breakdown": {
                "source_credibility": {
                    "score": source_score,
                    "weight": self.weights["source_credibility"],
                    "contribution": source_score * self.weights["source_credibility"],
                    "factors": self._explain_source_score(article),
                },
                "recency": {
                    "score": recency_score,
                    "weight": self.weights["recency"],
                    "contribution": recency_score * self.weights["recency"],
                    "factors": self._explain_recency_score(article),
                },
                "content_quality": {
                    "score": content_score,
                    "weight": self.weights["content_quality"],
                    "contribution": content_score * self.weights["content_quality"],
                    "factors": self._explain_content_score(article),
                },
                "engagement_potential": {
                    "score": engagement_score,
                    "weight": self.weights["engagement_potential"],
                    "contribution": engagement_score
                    * self.weights["engagement_potential"],
                    "factors": self._explain_engagement_score(article),
                },
            },
            "key_strengths": self._identify_strengths(
                article, source_score, recency_score, content_score, engagement_score
            ),
            "improvement_areas": self._identify_improvement_areas(
                article, source_score, recency_score, content_score, engagement_score
            ),
            "recommendation": (
                "include"
                if final_score >= get_runtime_config().scoring_config["minimum_score"]
                else "exclude"
            ),
        }

        return explanation

    def _get_overall_assessment(self, score: float) -> str:
        """Convierte score numérico a evaluación cualitativa."""
        if score >= 0.8:
            return "excelente"
        elif score >= 0.6:
            return "muy bueno"
        elif score >= 0.4:
            return "bueno"
        elif score >= 0.2:
            return "regular"
        else:
            return "bajo"

    def _explain_source_score(self, article: Article) -> List[str]:
        """Explica los factores que contribuyeron al score de fuente."""
        factors = []

        if article.peer_reviewed:
            factors.append("Artículo peer-reviewed (+)")
        elif article.is_preprint:
            factors.append("Preprint sin peer review (-)")

        if article.doi:
            factors.append("Tiene DOI (+)")

        if article.journal:
            factors.append(f"Publicado en {article.journal}")

        return factors

    def _explain_recency_score(self, article: Article) -> List[str]:
        """Explica los factores de recencia."""
        factors = []

        if article.published_date:
            # Normalize date for safety
            pub_date = article.published_date
            if pub_date.tzinfo is None:
                pub_date = pub_date.replace(tzinfo=timezone.utc)
            else:
                pub_date = pub_date.astimezone(timezone.utc)

            age = datetime.now(timezone.utc) - pub_date
            if age.days == 0:
                factors.append("Publicado hoy (+)")
            elif age.days <= 3:
                factors.append(f"Publicado hace {age.days} días (+)")
            elif age.days <= 7:
                factors.append(f"Publicado hace {age.days} días")
            else:
                factors.append(f"Publicado hace {age.days} días (-)")
        else:
            factors.append("Fecha de publicación desconocida (-)")

        return factors

    def _explain_content_score(self, article: Article) -> List[str]:
        """Explica los factores de calidad de contenido."""
        factors = []

        content_length = len((article.title or "") + " " + (article.summary or ""))
        if content_length >= 300:
            factors.append("Longitud de contenido apropiada (+)")
        else:
            factors.append("Contenido relativamente corto (-)")

        # Analizar título
        if article.title and len(article.title) > 30:
            factors.append("Título descriptivo (+)")

        return factors

    def _explain_engagement_score(self, article: Article) -> List[str]:
        """Explica los factores de potencial de engagement."""
        factors = []

        full_text = f"{article.title or ''} {article.summary or ''}".lower()

        if any(word in full_text for word in ["breakthrough", "discovery", "first"]):
            factors.append("Contiene palabras de impacto (+)")

        if any(topic in full_text for topic in ["ai", "climate", "covid"]):
            factors.append("Trata temas trending (+)")

        return factors

    def _identify_strengths(self, article: Article, *scores) -> List[str]:
        """Identifica las principales fortalezas del artículo."""
        strengths = []
        source_score, recency_score, content_score, engagement_score = scores

        if source_score >= 0.8:
            strengths.append("Fuente muy confiable")
        if recency_score >= 0.8:
            strengths.append("Muy reciente")
        if content_score >= 0.8:
            strengths.append("Contenido de alta calidad")
        if engagement_score >= 0.8:
            strengths.append("Alto potencial viral")

        return strengths

    def _identify_improvement_areas(self, article: Article, *scores) -> List[str]:
        """Identifica áreas donde el artículo podría mejorar."""
        areas = []
        source_score, recency_score, content_score, engagement_score = scores

        if source_score < 0.4:
            areas.append("Credibilidad de fuente limitada")
        if recency_score < 0.4:
            areas.append("Contenido no muy reciente")
        if content_score < 0.4:
            areas.append("Calidad de contenido mejorable")
        if engagement_score < 0.4:
            areas.append("Potencial de engagement limitado")

        return areas


# Funciones de utilidad para el scoring
# ====================================


def score_multiple_articles(
    articles: List[Article], scorer: BasicScorer | None = None
) -> Dict[str, Any]:
    """
    Aplica scoring a múltiples artículos y genera estadísticas.

    Esta función es útil para procesar lotes de artículos de manera eficiente.
    """
    if not scorer:
        scorer = BasicScorer()

    results: List[Dict[str, Any]] = []
    included_articles = 0
    excluded_articles = 0
    score_distribution: Dict[str, int] = {
        "excellent": 0,
        "very_good": 0,
        "good": 0,
        "fair": 0,
        "poor": 0,
    }

    total_score = 0.0

    for article in articles:
        try:
            score_result = scorer.score_article(article)
            results.append(
                {
                    "article_id": article.id,
                    "title": article.title,
                    "score_result": score_result,
                }
            )

            final_score = float(score_result.get("final_score", 0.0))
            total_score += final_score

            if bool(score_result.get("should_include")):
                included_articles += 1
            else:
                excluded_articles += 1

            # Actualizar distribución
            if final_score >= 0.8:
                score_distribution["excellent"] += 1
            elif final_score >= 0.6:
                score_distribution["very_good"] += 1
            elif final_score >= 0.4:
                score_distribution["good"] += 1
            elif final_score >= 0.2:
                score_distribution["fair"] += 1
            else:
                score_distribution["poor"] += 1

        except Exception as e:
            logger.error(f"Error scoring artículo {article.id}: {e}")
            continue

    average_score = (total_score / len(articles)) if articles else 0.0
    stats: Dict[str, Any] = {
        "total_articles": len(articles),
        "included_articles": included_articles,
        "excluded_articles": excluded_articles,
        "average_score": average_score,
        "score_distribution": score_distribution,
    }
    return {"results": results, "statistics": stats}


# ¿Por qué esta arquitectura de scoring?
# =====================================
#
# 1. TRANSPARENCIA TOTAL: Cada score se explica completamente,
#    permitiendo entender y mejorar las decisiones.
#
# 2. MULTIDIMENSIONAL: Evalúa múltiples aspectos relevantes
#    para tomar decisiones más informadas.
#
# 3. CONFIGURABLE: Los pesos se pueden ajustar según necesidades
#    cambiantes o feedback de usuarios.
#
# 4. EXTENSIBLE: Fácil agregar nuevas dimensiones o factores
#    de evaluación sin romper el código existente.
#
# 5. ROBUSTO: Manejo de errores y casos edge para funcionar
#    con datos del mundo real, que siempre son imperfectos.
#
# 6. PERFORMANTE: Optimizado para procesar grandes volúmenes
#    de artículos de manera eficiente.
#
# Este sistema de scoring es como tener un panel de expertos
# que nunca se cansa, siempre es consistente, y puede explicar
# exactamente por qué tomó cada decisión.
