# config/sources.py
# Catálogo de fuentes RSS para News Collector
# ===========================================

"""
Este archivo define todas las fuentes de información que nuestro sistema
monitoreará. Piensa en esto como crear una biblioteca curada de las mejores
fuentes científicas del mundo, cada una con su propia personalidad y fortalezas.

Cada fuente tiene atributos que nos ayudan a entender su naturaleza:
- credibility_score: Qué tan confiable es (0.0 a 1.0)
- update_frequency: Qué tan seguido publican
- category: Área científica principal
- language: Idioma del contenido
- impact_factor: Influencia en la comunidad científica
"""

# Configuración de fuentes RSS organizadas por categoría
# =====================================================

# Journals Científicos de Élite (Impact Factor > 10)
# ==================================================
# Estas son las revistas más prestigiosas del mundo científico,
# equivalentes a los periódicos más importantes pero para ciencia.

ELITE_JOURNALS = {
    "nature": {
        "name": "Nature",
        "url": "https://www.nature.com/nature.rss",
        "credibility_score": 1.0,  # Máxima credibilidad
        "update_frequency": "weekly",
        "category": "multidisciplinary",
        "language": "en",
        "impact_factor": 49.962,
        "description": "La revista científica más prestigiosa del mundo",
        "typical_delay": 0,  # Horas entre publicación y disponibilidad en RSS
    },
    "science": {
        "name": "Science",
        "url": "https://science.sciencemag.org/rss/current.xml",
        "credibility_score": 1.0,
        "update_frequency": "weekly",
        "category": "multidisciplinary",
        "language": "en",
        "impact_factor": 47.728,
        "description": "Revista insignia de la AAAS, rival histórico de Nature",
        "typical_delay": 0,
    },
    "cell": {
        "name": "Cell",
        "url": "https://www.cell.com/cell/current.rss",
        "credibility_score": 0.98,
        "update_frequency": "biweekly",
        "category": "biology",
        "language": "en",
        "impact_factor": 38.637,
        "description": "La revista más importante en biología celular y molecular",
        "typical_delay": 1,
    },
    "nejm": {
        "name": "New England Journal of Medicine",
        "url": "https://www.nejm.org/action/showFeed?jc=nejm&type=etoc&feed=rss",
        "credibility_score": 0.99,
        "update_frequency": "weekly",
        "category": "medicine",
        "language": "en",
        "impact_factor": 91.245,
        "description": "La biblia de la medicina clínica",
        "typical_delay": 0,
    },
}

# Medios Científicos Especializados
# =================================
# Estos no son journals académicos, pero son medios especializados
# que traducen la ciencia compleja para audiencias más amplias.

SCIENCE_MEDIA = {
    "scientific_american": {
        "name": "Scientific American",
        "url": "https://rss.sciam.com/ScientificAmerican-Global",
        "credibility_score": 0.85,
        "update_frequency": "daily",
        "category": "popular_science",
        "language": "en",
        "impact_factor": None,  # No aplica para medios
        "description": "Divulgación científica de alta calidad desde 1845",
        "typical_delay": 2,
    },
    "new_scientist": {
        "name": "New Scientist",
        "url": "https://www.newscientist.com/feed/home/",
        "credibility_score": 0.80,
        "update_frequency": "daily",
        "category": "popular_science",
        "language": "en",
        "impact_factor": None,
        "description": "Enfoque en ciencia emergente y tendencias futuras",
        "typical_delay": 1,
    },
    "ars_technica": {
        "name": "Ars Technica Science",
        "url": "https://feeds.arstechnica.com/arstechnica/science",
        "credibility_score": 0.82,
        "update_frequency": "daily",
        "category": "technology",
        "language": "en",
        "impact_factor": None,
        "description": "Excelente cobertura de tecnología y ciencia aplicada",
        "typical_delay": 0,
    },
    "phys_org": {
        "name": "Phys.org",
        "url": "https://phys.org/rss-feed/",
        "credibility_score": 0.75,
        "update_frequency": "multiple_daily",
        "category": "multidisciplinary",
        "language": "en",
        "impact_factor": None,
        "description": "Agregador de noticias científicas de universidades",
        "typical_delay": 0,
    },
}

# Fuentes Institucionales
# =======================
# Estas son organizaciones oficiales que publican sus propios descubrimientos.
# Son muy confiables porque vienen directamente de la fuente.

INSTITUTIONAL_SOURCES = {
    "mit_news": {
        "name": "MIT News",
        "url": "https://news.mit.edu/rss/feed",
        "credibility_score": 0.90,
        "update_frequency": "daily",
        "category": "technology",
        "language": "en",
        "impact_factor": None,
        "description": "Investigación de una de las mejores universidades técnicas",
        "typical_delay": 0,
    },
    "stanford_news": {
        "name": "Stanford News",
        "url": "https://news.stanford.edu/feed/",
        "credibility_score": 0.90,
        "update_frequency": "daily",
        "category": "multidisciplinary",
        "language": "en",
        "impact_factor": None,
        "description": "Investigación de Stanford, especialmente fuerte en AI y medicina",
        "typical_delay": 0,
    },
    "nasa_news": {
        "name": "NASA News",
        "url": "https://www.nasa.gov/rss/dyn/breaking_news.rss",
        "credibility_score": 0.95,
        "update_frequency": "daily",
        "category": "space",
        "language": "en",
        "impact_factor": None,
        "description": "Noticias espaciales de la fuente más autorizada",
        "typical_delay": 0,
    },
    "nih_news": {
        "name": "NIH News",
        "url": "https://www.nih.gov/news-events/news-releases/rss.xml",
        "credibility_score": 0.95,
        "update_frequency": "weekly",
        "category": "medicine",
        "language": "en",
        "impact_factor": None,
        "description": "Instituto Nacional de Salud, máxima autoridad médica de EE.UU.",
        "typical_delay": 0,
    },
}

# Repositorios de Preprints
# ========================
# Estos sitios publican investigación antes de peer review.
# Son importantes para capturar ciencia de vanguardia, pero necesitan
# tratamiento especial porque no están peer-reviewed.

PREPRINT_SOURCES = {
    "arxiv_ai": {
        "name": "arXiv AI/ML",
        "url": "http://export.arxiv.org/rss/cs.AI+cs.LG+cs.CL+cs.CV",
        "credibility_score": 0.70,  # Menor porque no está peer-reviewed
        "update_frequency": "daily",
        "category": "artificial_intelligence",
        "language": "en",
        "impact_factor": None,
        "description": "Preprints de inteligencia artificial y machine learning",
        "typical_delay": 0,
        "special_handling": "preprint",  # Marca especial para procesamiento
    },
    "biorxiv": {
        "name": "bioRxiv",
        "url": "https://connect.biorxiv.org/biorxiv_xml.php?subject=all",
        "credibility_score": 0.65,
        "update_frequency": "daily",
        "category": "biology",
        "language": "en",
        "impact_factor": None,
        "description": "Preprints de biología y ciencias de la vida",
        "typical_delay": 0,
        "special_handling": "preprint",
    },
}

# Consolidación de todas las fuentes
# ==================================
# Aquí combinamos todas las categorías en una estructura unificada

ALL_SOURCES = {
    **ELITE_JOURNALS,
    **SCIENCE_MEDIA,
    **INSTITUTIONAL_SOURCES,
    **PREPRINT_SOURCES,
}

# Configuraciones específicas por categoría
# =========================================

CATEGORY_CONFIG = {
    "multidisciplinary": {
        "priority_multiplier": 1.0,
        "min_score_threshold": 0.3,
        "max_daily_articles": 15,
    },
    "medicine": {
        "priority_multiplier": 1.2,  # Medicina es muy importante
        "min_score_threshold": 0.4,
        "max_daily_articles": 12,
    },
    "artificial_intelligence": {
        "priority_multiplier": 1.1,
        "min_score_threshold": 0.35,
        "max_daily_articles": 10,
    },
    "technology": {
        "priority_multiplier": 1.0,
        "min_score_threshold": 0.3,
        "max_daily_articles": 8,
    },
    "space": {
        "priority_multiplier": 0.9,
        "min_score_threshold": 0.3,
        "max_daily_articles": 6,
    },
    "biology": {
        "priority_multiplier": 0.95,
        "min_score_threshold": 0.3,
        "max_daily_articles": 8,
    },
    "popular_science": {
        "priority_multiplier": 0.8,  # Menos peso por ser divulgación
        "min_score_threshold": 0.25,
        "max_daily_articles": 5,
    },
}

# Funciones de utilidad para trabajar con fuentes
# ===============================================


def get_sources_by_category(category):
    """
    Devuelve todas las fuentes de una categoría específica.
    Útil para recolección selectiva por tema.
    """
    return {
        source_id: source_config
        for source_id, source_config in ALL_SOURCES.items()
        if source_config["category"] == category
    }


def get_high_credibility_sources(min_credibility=0.85):
    """
    Devuelve solo las fuentes con alta credibilidad.
    Útil para noticias breaking o cuando queremos máxima confianza.
    """
    return {
        source_id: source_config
        for source_id, source_config in ALL_SOURCES.items()
        if source_config["credibility_score"] >= min_credibility
    }


def get_sources_by_update_frequency(frequency):
    """
    Devuelve fuentes que se actualizan con cierta frecuencia.
    Útil para optimizar la frecuencia de recolección.
    """
    return {
        source_id: source_config
        for source_id, source_config in ALL_SOURCES.items()
        if source_config["update_frequency"] == frequency
    }


# Validación de fuentes
# ====================


def validate_sources():
    """
    Verifica que todas las fuentes estén bien configuradas.
    Es como hacer un control de calidad de nuestra biblioteca.
    """
    required_fields = ["name", "url", "credibility_score", "category", "language"]

    for source_id, source_config in ALL_SOURCES.items():
        # Verificar campos requeridos
        for field in required_fields:
            if field not in source_config:
                raise ValueError(f"Fuente {source_id} le falta el campo {field}")

        # Verificar rangos válidos
        credibility = source_config["credibility_score"]
        if not 0.0 <= credibility <= 1.0:
            raise ValueError(f"Credibilidad de {source_id} debe estar entre 0.0 y 1.0")

        # Verificar URL válida (básicamente)
        url = source_config["url"]
        if not url.startswith(("http://", "https://")):
            raise ValueError(f"URL de {source_id} no es válida: {url}")

    print(f"✅ {len(ALL_SOURCES)} fuentes validadas correctamente")


# ¿Por qué esta estructura de fuentes?
# ====================================
#
# 1. JERARQUÍA DE CREDIBILIDAD: Journals > Instituciones > Medios > Preprints
#    Esto nos permite pesar las noticias según su fuente
#
# 2. DIVERSIDAD TEMÁTICA: Cubrimos todas las áreas principales de ciencia
#    para ser comprehensivos
#
# 3. METADATOS RICOS: Cada fuente tiene información que nos ayuda a
#    procesarla apropiadamente
#
# 4. ESCALABILIDAD: Fácil agregar nuevas fuentes sin tocar código
#
# 5. CONFIGURACIÓN POR CATEGORÍA: Diferentes reglas para diferentes tipos
#    de ciencia
#
# Este catálogo es como tener un bibliotecario experto que conoce
# perfectamente cada fuente y puede recomendarte la mejor para cada tema.
