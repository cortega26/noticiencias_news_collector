# Estructura del proyecto News Collector
# =====================================

# Directorio raíz del proyecto: news_collector/
#
# news_collector/
# ├── main.py                 # Punto de entrada principal del sistema
# ├── config/
# │   ├── __init__.py
# │   ├── settings.py         # Configuración general del sistema
# │   └── sources.py          # Definición de fuentes RSS y APIs
# ├── src/
# │   ├── __init__.py
# │   ├── collectors/
# │   │   ├── __init__.py
# │   │   ├── rss_collector.py    # Colector de feeds RSS
# │   │   └── base_collector.py   # Clase base para todos los colectores
# │   ├── processors/
# │   │   ├── __init__.py
# │   │   ├── content_analyzer.py # Análisis de contenido de artículos
# │   │   └── deduplicator.py     # Eliminación de duplicados
# │   ├── scoring/
# │   │   ├── __init__.py
# │   │   └── basic_scorer.py     # Sistema de puntuación inicial
# │   ├── storage/
# │   │   ├── __init__.py
# │   │   ├── database.py         # Manejo de base de datos
# │   │   └── models.py           # Modelos de datos
# │   └── utils/
# │       ├── __init__.py
# │       ├── logger.py           # Sistema de logging
# │       └── helpers.py          # Funciones de utilidad
# ├── data/
# │   ├── news.db                 # Base de datos SQLite
# │   └── logs/                   # Archivos de log
# ├── tests/
# │   ├── __init__.py
# │   └── test_collectors.py      # Tests unitarios
# ├── requirements.txt            # Dependencias Python
# ├── README.md                   # Documentación del proyecto
# └── run_collector.py            # Script para ejecutar el colector

# ¿Por qué esta estructura?
# ========================
#
# 1. SEPARACIÓN DE RESPONSABILIDADES:
#    Cada directorio tiene una función específica, lo que hace el código
#    más fácil de mantener y extender
#
# 2. ESCALABILIDAD:
#    Puedes agregar nuevos tipos de colectores sin tocar el código existente
#
# 3. TESTABILIDAD:
#    Cada componente puede probarse independientemente
#
# 4. CONFIGURACIÓN CENTRALIZADA:
#    Todas las configuraciones están en un lugar, fácil de modificar
#
# 5. MODULARIDAD:
#    Cada módulo hace una cosa y la hace bien, siguiendo principios SOLID
