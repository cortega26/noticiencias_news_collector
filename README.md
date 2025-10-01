# 🧬 News Collector System

## Sistema Automatizado de Recopilación y Scoring de Noticias Científicas

[![CI Status](https://img.shields.io/endpoint?url=https://gist.githubusercontent.com/noticiencias/<CI_BADGE_GIST_ID>/raw/ci-badge.json)](https://github.com/noticiencias/noticiencias_news_collector/actions/workflows/ci.yml?query=branch%3Amain+event%3Apush)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Status: MVP](https://img.shields.io/badge/Status-MVP-green.svg)]()

> ℹ️ Sustituye `<CI_BADGE_GIST_ID>` por el identificador real del gist configurado en el secreto `CI_BADGE_GIST_ID` y crea el secreto `CI_BADGE_PAT` con un token que tenga permisos `repo` y `gist`.

Un sistema inteligente que recopila automáticamente noticias científicas de las mejores fuentes del mundo, las evalúa mediante un algoritmo de scoring multidimensional, y selecciona las más importantes para tu audiencia.

---

## 🎯 ¿Qué hace este sistema?

Imagina tener un asistente de investigación súper inteligente que:

- **🔍 Explora** las mejores fuentes científicas del mundo (Nature, Science, MIT News, etc.)
- **🧠 Evalúa** cada artículo según credibilidad, recencia, calidad y potencial de engagement
- **⭐ Selecciona** automáticamente los descubrimientos más importantes
- **📊 Proporciona** scores transparentes y explicaciones detalladas
- **🚀 Funciona** 24/7 sin supervisión

Eso es exactamente lo que hace este sistema.

---

## 🏗️ Arquitectura de Referencia

```mermaid
graph TD
    Scheduler[Scheduler] --> Collectors[Collectors]
    Collectors --> Parsers[Parser & Normalizer]
    Parsers --> Dedupe[Canonicalización & Dedupe]
    Dedupe --> Enrichment[Enrichment]
    Enrichment --> Scoring[Scoring]
    Scoring --> Reranker[Reranker]
    Reranker --> Storage[Storage]
    Storage --> Serving[Serving]
    Storage --> Monitoring[Monitoring]
```

- Contratos clave: [Event Envelope v1](AGENTS.md#11-event-envelope-v1), [Article Entity v2](AGENTS.md#12-article-entity-v2), [Cluster Record v1](AGENTS.md#13-cluster-record-v1), [Score Explanation v1](AGENTS.md#14-score-explanation-v1).
- Cada componente publica logs estructurados (`trace_id`, `source_id`, `article_id`) descritos en el [Runbook Operacional](docs/runbook.md).
- Para flujos de resolución de incidentes específicos del colector revisa el [Collector Runbook](docs/collector_runbook.md).

## ✨ Características Principales

### 🤖 Recolección Inteligente
- **Fuentes Premium**: Nature, Science, Cell, NEJM, MIT News, Stanford News, NASA, y más
- **Múltiples Formatos**: RSS, Atom, feeds institucionales
- **Respeto por Servidores**: Rate limiting inteligente, manejo de errores robusto
  - Feeds comunitarios (ej. r/science) se consultan como máximo una vez por minuto para respetar el rate limit de Reddit (intervalos >=30s y user-agent dedicado)
  - Configuraciones como `min_delay_seconds` por fuente y `RATE_LIMITING_CONFIG["domain_overrides"]` aseguran tiempos de espera adicionales cuando un host lo exige (ej. arXiv = 20s, Reddit = 30s)
- **Caching Condicional**: Persistimos `ETag` y `Last-Modified` por fuente para enviar `If-None-Match`/`If-Modified-Since`, reduciendo ancho de banda y evitando descargas innecesarias cuando no hay contenido nuevo.
- **Modo Asíncrono Opcional**: al activar `ASYNC_ENABLED=true` el colector usa `httpx.AsyncClient` y un `asyncio.Semaphore` controlado por `MAX_CONCURRENT_REQUESTS` para paralelizar dominios distintos sin saltarse `robots.txt`, deduplicación ni límites por dominio.
- **Deduplicación**: Detección automática de contenido duplicado

### 🧠 Scoring Multidimensional
- **Credibilidad de Fuente** (30%): pondera el prestigio de la fuente.
- **Freshness Decay** (25%): aplica una caída exponencial según horas desde la publicación.
- **Calidad de Contenido** (25%): valora densidad/riqueza del artículo y entidades detectadas.
- **Engagement Potencial** (20%): combina sentimiento y señales de interacción.
- **Penalización de Diversidad**: resta puntos a duplicados del mismo cluster para priorizar variedad.

Cada artículo incluye un payload de "why ranked" con contribuciones por feature, pesos y penalizaciones.

### 🔁 Reranker Determinístico
- Limita el porcentaje de artículos por fuente y por tema en el top-K.
- Reordena con desempate: score → recencia → fuente → random seed.
- Configurable mediante `SOURCE_CAP_PERCENTAGE`, `TOPIC_CAP_PERCENTAGE`, `RERANKER_SEED`.

### 📊 Transparencia Total
- Cada score se explica completamente
- Desglose detallado por componente
- Trazabilidad de decisiones
- Métricas de performance en tiempo real

### 📈 Evaluación Offline
- `python scripts/evaluate_ranking.py` → NDCG@5, Precision@5, MRR sobre un dev set.
- `python scripts/reranker_distribution.py` → distribución de fuentes/temas antes vs. después del reranker.
- `python scripts/enrichment_sanity.py` → sanity check de enriquecimiento (lenguaje, sentimiento, tópicos, entidades).
- `python scripts/weekly_quality_report.py tests/data/monitoring/outage_replay.json` → genera reporte semanal en formato común.
- `python scripts/replay_outage.py tests/data/monitoring/outage_replay.json` → replay de outage histórico con alertas canario.
- Ver especificación del formato en `docs/common_output_format.md`.

### 🛠️ Facilidad de Uso
- **Instalación Simple**: Una línea de comando
- **Configuración Flexible**: Variables de entorno
- **Múltiples Interfaces**: CLI, API programática
- **Logging Comprehensivo**: Observabilidad completa (estructura y campos obligatorios en el [Runbook Operacional](docs/runbook.md))
- **Runbooks Accionables**: Guías paso a paso en [docs/runbook.md](docs/runbook.md) y [docs/collector_runbook.md](docs/collector_runbook.md)

---

## 🚀 Instalación Rápida

### Prerrequisitos
- Python 3.10 o superior (probado en 3.13)
- Git

### 1. Clonar el Repositorio
> ℹ️ El repositorio es privado. Asegúrate de tener acceso autorizado (SSH o token personal) antes de clonar.

```bash
# Usando SSH (recomendado)
git clone git@github.com:noticiencias/noticiencias_news_collector.git
cd noticiencias_news_collector

# Usando HTTPS + token personal
git clone https://github.com/noticiencias/noticiencias_news_collector.git
cd noticiencias_news_collector
```

### 2. Crear y activar entorno virtual (recomendado)
```bash
# Windows (PowerShell)
python -m venv .venv
.venv\Scripts\Activate.ps1

# macOS/Linux
python3 -m venv .venv
source .venv/bin/activate
```

> 💡 Si prefieres automatizar estos pasos, el comando `make bootstrap` crea el entorno virtual e instala cada dependencia por ti.

### 3. Instalar Dependencias (Makefile recomendado)
```bash
make bootstrap
```

> 💡 ¿Actualizaste `requirements.txt`? Regenera el lock ejecutando:
> ```bash
> python -m piptools compile --generate-hashes --output-file requirements.lock requirements.txt
> ```

### 4. Verificar Instalación
```bash
make test
```

### 5. Configurar Entorno
El proyecto usa [`python-dotenv`](https://github.com/theskumar/python-dotenv) para cargar variables desde un archivo `.env`.
El template [`.env.example`](.env.example) documenta todos los parámetros admitidos y agrupa las opciones por secciones
(`runtime`, `database`, `collection`, `scoring`, etc.). Copia el archivo y ajusta los valores según tu escenario:

```bash
cp .env.example .env
# Edita .env para habilitar Postgres, ajustar rate limits o personalizar el scoring.
```

> ℹ️ Si vas a usar PostgreSQL, descomenta el bloque `# Database configuration` y reemplaza las credenciales. Para entornos de
> operación consulta también las secciones `# Operational scripts` y `# Logging`.

### 🖥️ Editor de Configuración

La herramienta `tools.config_editor` permite inspeccionar y modificar cualquier archivo de configuración soportado
(`.env`, YAML, JSON, TOML o módulos `config.py`) desde una interfaz Tkinter o en modo headless con las mismas validaciones.

- **GUI rápida**: `make config-gui CONFIG_PATH=$(PWD)` abre la ventana y recuerda tamaño/posición.
- **Headless para CI**: `make config-set KEY="ingest.timeout=45" PROFILE=dev EXTRA="debug=false"` actualiza varios valores sin GUI.
- **CLI directo**:

  ```bash
  python -m tools.config_editor --config config --profile dev
  python -m tools.config_editor --config config --set ingest.timeout=30 --profile prod
  ```

> 🛡️ Cada guardado valida los tipos, escribe de forma atómica y crea un respaldo con timestamp en `./backups/` sin exponer secretos en logs (`logs/config_editor.log`).

### 6. Ejecutar Primera Recolección
```bash
python run_collector.py --dry-run
```

Si usas VS Code, selecciona el intérprete del entorno virtual:
```
.venv\Scripts\python.exe  (Windows)
.venv/bin/python           (macOS/Linux)
```

¡Con eso basta! El sistema ejecutará una simulación y te mostrará cómo funcionaría.

---

## 🎮 Uso Básico

### Recolección Simple
```bash
# Recolección completa de todas las fuentes
python run_collector.py

# Modo simulación (no guarda datos)
python run_collector.py --dry-run

# Fuentes específicas
python run_collector.py --sources nature science mit_news

# Modo silencioso
python run_collector.py --quiet
```

### Ver Fuentes Disponibles
```bash
python run_collector.py --list-sources
```

### Verificar Dependencias
```bash
python run_collector.py --check-deps
```

### Healthcheck Operativo
```bash
python run_collector.py --healthcheck
```
- Verifica conectividad con la base de datos, backlog en la cola de artículos pendientes y la frescura de la última ingesta.
- Consulta el runbook completo en [`docs/runbook.md`](docs/runbook.md) para flujos de diagnóstico y resolución cuando el healthcheck falle.

### Ejecutar en contenedor (experimental)
```bash
# Construye la imagen con la etiqueta sugerida (fecha UTC + short SHA)
export TAG="$(date -u +%Y%m%d).$(git rev-parse --short HEAD)"
docker build -t noticiencias/collector:${TAG} .

# Ejecuta la imagen con la configuración incluida y realiza un dry-run
docker run --rm \
    noticiencias/collector:${TAG} --dry-run
```

El workflow `Release` empaqueta automáticamente la imagen `noticiencias/collector:<fecha>.<sha>` como artefacto. Cada ejecución adjunta un archivo `image-run.md` con instrucciones para cargarla mediante `docker load` y repetir los pasos de bootstrap dentro del contenedor.

---

## 📚 Fuentes Configuradas

### 🏆 Journals de Élite
- **Nature** - La revista científica más prestigiosa del mundo
- **Science** - Revista insignia de la AAAS
- **Cell** - Líder en biología celular y molecular  
- **NEJM** - La biblia de la medicina clínica

### 🎓 Fuentes Institucionales
- **MIT News** - Instituto de Tecnología de Massachusetts
- **Stanford News** - Universidad de Stanford
- **NASA News** - Agencia Espacial NASA
- **NIH News** - Instituto Nacional de Salud

### 📰 Medios Especializados
- **Scientific American** - Divulgación científica de calidad
- **New Scientist** - Ciencia emergente y tendencias
- **Ars Technica** - Tecnología y ciencia aplicada
- **Phys.org** - Agregador de noticias universitarias

### 📑 Repositorios de Preprints
- **arXiv** - Preprints de IA y Machine Learning
- **bioRxiv** - Preprints de biología y ciencias de la vida

### 🌐 Fuentes Comunitarias
- **r/science** - Subreddit moderado de divulgación científica (consulta limitada para respetar a Reddit)

---

## ⚙️ Configuración Avanzada

### Variables de Entorno Principales

```bash
# Colector RSS (sincrónico por defecto)
ASYNC_ENABLED=false               # true → usa AsyncRSSCollector
MAX_CONCURRENT_REQUESTS=8         # techo global de corrutinas

# Frecuencia de recolección (horas)
COLLECTION_INTERVAL=6

# Número de mejores artículos diarios
DAILY_TOP_COUNT=10

# Score mínimo para incluir artículos
MINIMUM_SCORE=0.3

# Scoring (modo por defecto = advanced)
SCORING_MODE=advanced               # basic / advanced

# Pesos legacy (modo basic)
WEIGHT_SOURCE=0.25
WEIGHT_RECENCY=0.20
WEIGHT_CONTENT=0.25
WEIGHT_ENGAGEMENT=0.30

# Pesos modo advanced (deben sumar 1.0)
FEATURE_WEIGHT_SOURCE=0.30
FEATURE_WEIGHT_FRESHNESS=0.25
FEATURE_WEIGHT_CONTENT=0.25
FEATURE_WEIGHT_ENGAGEMENT=0.20

# Freshness decay
FRESHNESS_HALF_LIFE_HOURS=18
FRESHNESS_MAX_DECAY_HOURS=168

# Diversidad
DIVERSITY_PENALTY_WEIGHT=0.15
DIVERSITY_MAX_PENALTY=0.3

# Heurísticas de calidad de contenido
SCORING_TITLE_LENGTH_DIVISOR=120
SCORING_SUMMARY_LENGTH_DIVISOR=400
SCORING_ENTITY_TARGET_COUNT=5
SCORING_CONTENT_WEIGHT_TITLE=0.4
SCORING_CONTENT_WEIGHT_SUMMARY=0.4
SCORING_CONTENT_WEIGHT_ENTITY=0.2

# Heurísticas de engagement
SCORING_SENTIMENT_POSITIVE=0.7
SCORING_SENTIMENT_NEUTRAL=0.5
SCORING_SENTIMENT_NEGATIVE=0.6
SCORING_SENTIMENT_FALLBACK=0.5
SCORING_WORD_COUNT_DIVISOR=800
SCORING_ENGAGEMENT_EXTERNAL_WEIGHT=0.6
SCORING_ENGAGEMENT_LENGTH_WEIGHT=0.4

# Concurrencia de scoring
SCORING_WORKERS=4

# Reranker determinístico
SOURCE_CAP_PERCENTAGE=0.5
TOPIC_CAP_PERCENTAGE=0.6
RERANKER_SEED=1337
```

### Modo Asíncrono del Colector

Activa `ASYNC_ENABLED=true` cuando:

- Necesitas abarcar muchas fuentes I/O-bound en la misma ventana de recolección.
- Los tiempos de respuesta promedio de las fuentes son altos (>2 s) y quieres mejorar throughput sin abrir múltiples procesos.
- Ya validaste en `staging` que los hosts respetan `If-None-Match`/`If-Modified-Since` (el modo async mantiene los mismos validadores y dedupe).

Recomendaciones:

- Ajusta `MAX_CONCURRENT_REQUESTS` según la capacidad de salida del entorno (8–12 suele funcionar; valores mayores pueden saturar DNS o proxies).
- El colector sigue aplicando `robots.txt` y `min_delay_seconds` por dominio mediante locks; revisa Grafana → panel "collector wait time" tras el despliegue.
- Mantén `RATE_LIMITING_CONFIG["domain_overrides"]` actualizado: la ejecución asíncrona respeta esos límites pero incrementará la presión si hay muchos dominios sin override.

### Personalizar Pesos de Scoring

Para el modo *advanced* ajusta los feature weights:

```bash
# Breaking news (más frescura)
FEATURE_WEIGHT_FRESHNESS=0.40
FEATURE_WEIGHT_SOURCE=0.25
FEATURE_WEIGHT_CONTENT=0.20
FEATURE_WEIGHT_ENGAGEMENT=0.15

# Publicaciones académicas (mayor credibilidad)
FEATURE_WEIGHT_SOURCE=0.45
FEATURE_WEIGHT_CONTENT=0.30
FEATURE_WEIGHT_FRESHNESS=0.15
FEATURE_WEIGHT_ENGAGEMENT=0.10
```

¿Necesitas volver al algoritmo previo? Configura `SCORING_MODE=basic`.

### Ajustar heurísticas sin romper el scoring

El modo *advanced* expone controles finos para ajustar la sensibilidad del algoritmo sin introducir efectos secundarios inesperados:

- **Divisores de longitud (`SCORING_TITLE_LENGTH_DIVISOR`, `SCORING_SUMMARY_LENGTH_DIVISOR`, `SCORING_WORD_COUNT_DIVISOR`)**: definen cuántos caracteres/palabras consideramos "suficientes" antes de dar puntuación máxima. Útiles para adaptar el sistema a resúmenes más cortos o notas largas.
- **Peso de entidades (`SCORING_ENTITY_TARGET_COUNT`, `SCORING_CONTENT_WEIGHT_*`)**: controla cuánta relevancia damos a artículos con entidades enriquecidas. Mantén la suma de los pesos en `1.0` para conservar una escala estable.
- **Sentimiento y engagement (`SCORING_SENTIMENT_*`, `SCORING_ENGAGEMENT_*`)**: permite reforzar o suavizar la señal emocional del contenido. Todos los valores se validan para permanecer en el rango `[0, 1]` y los pesos deben sumar `1.0` para evitar sesgos.

El scorer valida estos parámetros al arrancar y levantará un `ValueError` si detecta divisores no positivos, pesos fuera de rango o sumas incorrectas. Así evitamos despliegues con configuraciones inconsistentes.

---

## 🔧 Uso Programático

### API Python

```python
from main import create_system

# Crear e inicializar sistema
system = create_system()
system.initialize()

# Ejecutar recolección
results = system.run_collection_cycle()

# Obtener mejores artículos
top_articles = system.get_top_articles(limit=10)

# Ver estadísticas
stats = system.get_system_statistics()
```

### Configuración Personalizada

```python
# Override de configuración
config_override = {
    'scoring_weights': {
        'source_credibility': 0.40,
        'recency': 0.30,
        'content_quality': 0.20,
        'engagement_potential': 0.10
    }
}

system = create_system(config_override)
```

---

## 📊 Entendiendo los Scores

### Componentes del Score

Cada artículo recibe un score de 0.0 a 1.0 basado en cuatro dimensiones:

#### 🏛️ Credibilidad de Fuente (25%)
- **1.0**: Nature, Science, NEJM
- **0.8**: Journals de alta calidad
- **0.6**: Medios especializados confiables
- **0.4**: Fuentes académicas estándar

#### ⏰ Recencia (20%)
- **1.0**: Publicado en la última hora
- **0.9**: Publicado hoy
- **0.7**: Publicado esta semana
- **0.3**: Publicado este mes

#### 📝 Calidad de Contenido (25%)
- Longitud apropiada del texto
- Presencia de terminología científica
- Estructura del título
- Diversidad de vocabulario

#### 🔥 Potencial de Engagement (30%)
- Palabras que indican descubrimientos importantes
- Temas trending en ciencia
- Accesibilidad para audiencia general
- "Factor wow" del contenido

### Interpretando Resultados

```
Score >= 0.8  ⭐⭐⭐⭐⭐  Excelente - Artículo destacado
Score >= 0.6  ⭐⭐⭐⭐    Muy bueno - Alta relevancia
Score >= 0.4  ⭐⭐⭐      Bueno - Relevante
Score >= 0.2  ⭐⭐        Regular - Consideración
Score <  0.2  ⭐          Bajo - Probablemente descartado
```

---

## 📁 Estructura del Proyecto

```
news_collector/
├── main.py                 # Orquestador principal
├── run_collector.py        # Script de ejecución simple
├── requirements.txt        # Dependencias Python
├── .env.example           # Configuración de ejemplo
│
├── config/                # Configuración del sistema
│   ├── __init__.py
│   ├── settings.py        # Configuración general
│   └── sources.py         # Catálogo de fuentes RSS
│
├── src/                   # Código fuente principal
│   ├── __init__.py
│   ├── collectors/        # Sistemas de recolección
│   │   ├── __init__.py
│   │   ├── base_collector.py
│   │   └── rss_collector.py
│   ├── scoring/           # Sistema de scoring
│   │   ├── __init__.py
│   │   ├── basic_scorer.py
│   │   └── feature_scorer.py
│   ├── reranker/          # Capa determinística de reordenamiento
│   │   ├── __init__.py
│   │   └── reranker.py
│   ├── storage/           # Persistencia de datos
│   │   ├── __init__.py
│   │   ├── database.py
│   │   └── models.py
│   └── utils/             # Utilidades
│       ├── __init__.py
│       └── logger.py
│
└── data/                  # Datos del sistema
    ├── news.db           # Base de datos SQLite
    └── logs/             # Archivos de log
```

---

## 🔍 Debugging y Troubleshooting

### Problemas Comunes

#### Error de Dependencias
```bash
# Verificar que todas las dependencias estén instaladas
python run_collector.py --check-deps

# Reinstalar dependencias
python -m pip install --require-hashes -r requirements.lock
```

#### Problemas de Red
```bash
# Aumentar timeout en .env
REQUEST_TIMEOUT=60
REQUEST_DELAY=2.0

# Verificar conectividad
ping www.nature.com
```

#### Base de Datos Corrupta
```bash
# Eliminar y recrear base de datos
rm data/news.db
python run_collector.py --dry-run  # Recreará la DB
```

### Modo Debug

```bash
# Activar logging detallado
export DEBUG=true
export LOG_LEVEL=DEBUG
python run_collector.py --verbose
```

### Logs Útiles

```bash
# Ver logs en tiempo real
tail -f data/logs/collector.log

# Buscar errores específicos
grep "ERROR" data/logs/collector.log

# Ver estadísticas de fuentes
grep "Artículo guardado" data/logs/collector.log | wc -l
```

---

## 🚀 Optimización y Performance

### Para Volúmenes Altos

1. **Usar PostgreSQL**:
```bash
# En .env
DB_TYPE=postgresql
DB_HOST=localhost
DB_NAME=news_collector
DB_USER=collector
DB_PASSWORD=secure_password
```

2. **Ajustar Paralelismo**:
```bash
# Reducir delay entre requests
REQUEST_DELAY=0.5

# Aumentar límite por fuente
MAX_ARTICLES_PER_SOURCE=100
```

3. **Optimizar Scoring**:
```bash
# Ser más selectivo
MINIMUM_SCORE=0.5
DAILY_TOP_COUNT=15
```

### Monitoreo

```python
# Obtener métricas de performance
stats = system.get_system_statistics()
print(f"Artículos procesados: {stats['daily_statistics']['articles_processed']}")
print(f"Tasa de éxito: {stats['database_health']['status']}")
```

---

## 🔮 Roadmap Futuro

### Versión 1.1 - Mejoras de Core
- Procesamiento paralelo de fuentes
- Cache inteligente para evitar re-processing
- API REST para acceso externo
- Dashboard web para monitoreo

### Versión 1.2 - ML Avanzado
- Modelos de ML para scoring mejorado
- Análisis de sentimientos
- Detección de temas trending automática
- Personalización basada en feedback

### Versión 1.3 - Integración
- Webhooks para notificaciones
- Integración con redes sociales
- Export a diferentes formatos (JSON, RSS, email)
- Slack/Discord bots

### Versión 2.0 - Escalabilidad
- Arquitectura distribuida
- Queue systems (Redis/RabbitMQ)
- Multi-idioma support
- Cloud deployment automático

---

## 🛡️ Audit & Guardrail

El repositorio incluye un escáner determinístico para encontrar TODOs, placeholders y código comentado que haya quedado pendiente.

### Ejecutar el escáner localmente

```bash
make audit-todos
```

Este comando genera los reportes en `reports/placeholders.{csv,json,md}` con el mismo número de hallazgos en cada formato.

### Actualizar la línea base

```bash
make audit-todos-baseline
```

Guarda los resultados actuales en `reports/placeholders.baseline.json`. Úsalo cuando conscientemente cierres o aceptes la deuda técnica existente.

### Verificar regresiones en CI o localmente

```bash
make audit-todos-check
```

Compara el estado actual contra la baseline y falla si aparecen hallazgos nuevos. Puedes permitir cierta tolerancia ajustando la variable `AUDIT_TODOS_MAX_NEW` antes de ejecutar el comando.

En GitHub Actions, el job `audit-todos` ejecuta esta verificación en cada push/PR, sube los reportes como artefactos y comenta en el Pull Request cuando aparecen pendientes nuevos.

---

## 🤝 Contribuir

¡Las contribuciones son bienvenidas! Aquí's cómo puedes ayudar:

### Reportar Issues
- Usa el template de issue en GitHub
- Incluye logs relevantes
- Describe pasos para reproducir

### Agregar Fuentes
1. Edita `config/sources.py`
2. Agrega tu fuente con metadata completa
3. Testea con `--sources tu_fuente --dry-run`
4. Crea Pull Request

### Mejorar Scoring
1. Modifica `src/scoring/feature_scorer.py` (o `basic_scorer.py` si trabajas en el modo legacy).
2. Ejecuta `python scripts/evaluate_ranking.py` y `python scripts/enrichment_sanity.py`.
3. Agrega/actualiza tests (golden set en `tests/test_enrichment_pipeline.py`).
4. Documenta los cambios en este README y abre un Pull Request.

---

## 📄 Licencia

Este proyecto está bajo la licencia MIT. Ver el archivo [LICENSE](LICENSE) para detalles.

---

## 🙏 Agradecimientos

- **Fuentes de Datos**: Gracias a todas las instituciones científicas que proporcionan feeds RSS públicos
- **Bibliotecas Open Source**: feedparser, requests, SQLAlchemy, loguru, y muchas otras
- **Comunidad Científica**: Por hacer la información accesible y verificable

---

## 📞 Soporte

- **Issues**: [GitHub Issues](https://github.com/noticiencias/noticiencias_news_collector/issues)
- **Discusiones**: [GitHub Discussions](https://github.com/noticiencias/noticiencias_news_collector/discussions)
- **Email**: n/a

---

## 🏆 Stats del Proyecto

Los siguientes indicadores provienen de la última ejecución verificada de la suite de performance y del replay operacional.

- **⚙️ Throughput pipeline (SQLite dev)**: 11.5 artículos/s end-to-end con ingestión p95 en 128 ms y enriquecimiento p95 en 72 ms.
- **🗄️ Throughput pipeline (perfil PostgreSQL simulado)**: 46.6 artículos/s end-to-end con ingestión p95 en 31.7 ms y pool `QueuePool(12/6)`.
- **🎯 Accuracy del scorer**: error absoluto medio 0.0, 100% de aciertos en `should_include` y ranking idéntico al dataset dorado.
- **📥 Escritura PostgreSQL**: 0.024 s de promedio por inserción (p95 57 ms, máx. 97 ms) durante una ráfaga de 60 artículos.
- **🛡️ Disponibilidad observada**: 50% de ratio de ingesta normalizado; 2 fuentes auto-suspendidas en el último replay semanal.

### 🛣️ Roadmap de Métricas

- Expandir el monitoreo activo a 15+ fuentes premium con cobertura continua.
- Escalar el throughput sostenido a 50 artículos/segundo en producción.
- Mantener disponibilidad ≥99.9% en ventanas mensuales.
- Automatizar el procesamiento de 1 000+ artículos/día.

---

*Construido con ❤️ para la comunidad científica hispanohablante*
