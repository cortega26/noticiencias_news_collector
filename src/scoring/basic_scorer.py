# src/scoring/basic_scorer.py
# Sistema de scoring inteligente para News Collector
# ================================================

"""
Este es el cerebro de nuestro sistema: el motor que decide qué noticias
son realmente importantes y merecen la atención de nuestra audiencia.

Piensa en esto como tener un panel de expertos que evalúa cada noticia
desde múltiples ángulos: ¿qué tan confiable es la fuente? ¿qué tan reciente
es? ¿qué tan bien escrita está? ¿qué probabilidad tiene de interesar a la gente?

El sistema está diseñado para ser transparente: no es una caja negra, sino
que explica exactamente por qué cada artículo recibió cierto puntaje.
"""

import math
import re
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
import logging

from ..storage.models import Article
from config.settings import SCORING_CONFIG, TEXT_PROCESSING_CONFIG

logger = logging.getLogger(__name__)


class BasicScorer:
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
        self.weights = weights or SCORING_CONFIG["weights"].copy()
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
        self._keyword_cache = {}

        logger.info(f"🧠 Scorer inicializado con pesos: {self.weights}")

    def score_article(
        self, article: Article, source_config: Dict[str, Any] = None
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
            should_include = final_score >= SCORING_CONFIG["minimum_score"]

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

            return result

        except Exception as e:
            logger.error(f"Error calculando score para artículo {article.id}: {e}")
            # Retornar score neutral en caso de error
            return {
                "final_score": 0.5,
                "should_include": False,
                "components": {"error": str(e)},
                "weights": self.weights.copy(),
                "explanation": {"error": f"Error en cálculo: {str(e)}"},
                "version": self.version,
                "calculated_at": datetime.now(timezone.utc).isoformat(),
            }

    def _calculate_source_credibility_score(
        self, article: Article, source_config: Dict[str, Any] = None
    ) -> float:
        """
        Evalúa la credibilidad de la fuente.

        Este método es como tener un experto en medios que conoce la reputación
        de cada fuente y puede evaluar qué tan confiable es la información.

        Factores considerados:
        - Credibilidad base de la fuente
        - Si es peer-reviewed vs preprint
        - Reputación del journal
        - Presencia de DOI
        """
        score = 0.0

        # Score base de la fuente (del archivo de configuración)
        if source_config:
            base_credibility = source_config.get("credibility_score", 0.5)
        else:
            # Fallback: extraer de metadatos del artículo
            meta = getattr(article, "article_metadata", None) or {}
            base_credibility = meta.get("credibility_score", 0.5)

        score += base_credibility * 0.6  # 60% del score viene de la fuente

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

        # Calcular edad en horas
        now = datetime.now(timezone.utc)
        age_hours = (now - reference_date).total_seconds() / 3600

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

    def _evaluate_journal_reputation(self, journal_name: str) -> float:
        """
        Evalúa la reputación de un journal científico.

        Este método usa una lista curada de journals prestigiosos.
        En una versión más avanzada, podríamos conectar con APIs
        de impact factors reales.
        """
        if not journal_name:
            return 0.0

        journal_lower = journal_name.lower()

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

    def _evaluate_title_quality(self, title: str) -> float:
        """
        Evalúa la calidad del título del artículo.

        Un buen título científico debe ser descriptivo, específico,
        y libre de clickbait.
        """
        if not title:
            return 0.0

        score = 0.5
        title_lower = title.lower()

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
        if re.search(r"\d+", title):  # Contiene números
            score += 0.1

        if re.search(r"university|institute|lab", title_lower):  # Instituciones
            score += 0.1

        # Penalizar títulos muy cortos o muy largos
        if len(title) < 30:
            score -= 0.2
        elif len(title) > 150:
            score -= 0.1

        return max(0.0, min(1.0, score))

    def _evaluate_text_quality(self, text: str) -> float:
        """
        Evalúa la calidad general del texto.

        Considera factores como diversidad de vocabulario,
        estructura de oraciones, y presencia de información técnica.
        """
        if not text or len(text) < 50:
            return 0.0

        score = 0.5

        # Evaluar diversidad de vocabulario
        words = re.findall(r"\w+", text.lower())
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

        technical_count = sum(1 for term in technical_terms if term in text.lower())
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
        boost_keywords = TEXT_PROCESSING_CONFIG["boost_keywords"]

        # Contar keywords encontrados
        found_keywords = sum(
            1 for keyword in boost_keywords if keyword.lower() in full_text
        )

        # Normalizar score (máximo si tiene 5+ keywords relevantes)
        score = min(1.0, found_keywords / 5.0)

        return score

    def _evaluate_title_engagement_potential(self, title: str) -> float:
        """
        Evalúa el potencial de engagement del título.

        Busca elementos que hacen títulos más compartibles en redes sociales.
        """
        if not title:
            return 0.0

        score = 0.5
        title_lower = title.lower()

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
        if re.search(r"\d+%|\d+ times|\d+ years", title):
            score += 0.1

        # Preguntas pueden ser engaging
        if "?" in title:
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
                if final_score >= SCORING_CONFIG["minimum_score"]
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
            age = datetime.now(timezone.utc) - article.published_date
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
    articles: List[Article], scorer: BasicScorer = None
) -> Dict[str, Any]:
    """
    Aplica scoring a múltiples artículos y genera estadísticas.

    Esta función es útil para procesar lotes de artículos de manera eficiente.
    """
    if not scorer:
        scorer = BasicScorer()

    results = []
    stats = {
        "total_articles": len(articles),
        "included_articles": 0,
        "excluded_articles": 0,
        "average_score": 0.0,
        "score_distribution": {
            "excellent": 0,
            "very_good": 0,
            "good": 0,
            "fair": 0,
            "poor": 0,
        },
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

            final_score = score_result["final_score"]
            total_score += final_score

            if score_result["should_include"]:
                stats["included_articles"] += 1
            else:
                stats["excluded_articles"] += 1

            # Actualizar distribución
            if final_score >= 0.8:
                stats["score_distribution"]["excellent"] += 1
            elif final_score >= 0.6:
                stats["score_distribution"]["very_good"] += 1
            elif final_score >= 0.4:
                stats["score_distribution"]["good"] += 1
            elif final_score >= 0.2:
                stats["score_distribution"]["fair"] += 1
            else:
                stats["score_distribution"]["poor"] += 1

        except Exception as e:
            logger.error(f"Error scoring artículo {article.id}: {e}")
            continue

    if len(articles) > 0:
        stats["average_score"] = total_score / len(articles)

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
