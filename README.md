# 🧬 News Collector System
_Plataforma modular para recolectar, enriquecer y priorizar noticias científicas con trazabilidad operativa completa._

[![CI Status](https://img.shields.io/endpoint?url=https://gist.githubusercontent.com/cortega26/d271be8cbb4914fcb020d48f5d06b9f1/raw/ci-badge.json)](.github/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Status: MVP](https://img.shields.io/badge/Status-MVP-green.svg)](CHANGELOG.md)

## Tabla de contenidos
1. [Descripción general](#descripción-general)
2. [Arquitectura / Flujo](#arquitectura--flujo)
3. [Instalación](#instalación)
4. [Configuración](#configuración)
5. [Uso](#uso)
6. [Scripts y evaluación offline](#scripts-y-evaluación-offline)
7. [Runbooks](#runbooks)
8. [Datos de entrada/salida](#datos-de-entrada-salida)
9. [Estructura del proyecto](#estructura-del-proyecto)
10. [Pruebas](#pruebas)
11. [CI/CD](#cicd)
12. [Performance y límites conocidos](#performance-y-límites-conocidos)
13. [Seguridad](#seguridad)
14. [Troubleshooting & FAQ](#troubleshooting--faq)
15. [Roadmap y limitaciones](#roadmap-y-limitaciones)
16. [Contribución](#contribución)
17. [Licencia y créditos](#licencia-y-créditos)
18. [Preguntas abiertas](#preguntas-abiertas)

## Descripción general
News Collector System automatiza la ingesta de fuentes científicas (journals, agencias, divulgadores), aplica limpieza y enriquecimiento lingüístico, calcula un puntaje multidimensional y genera listados priorizados para su publicación o consumo por APIs internas. Está pensado para equipos de datos/noticias que necesitan decisiones reproducibles, auditoría y herramientas de operación.

**Características clave**
- Catalogación de 15 fuentes curadas con metadatos de credibilidad y frecuencia.
- Pipelines determinísticos de deduplicación, enriquecimiento y scoring con explicación de cada feature.
- CLI central (`run_collector.py`) con modos de simulación, healthchecks y filtrado de fuentes.
- Herramientas de configuración (CLI y GUI) sobre un esquema validado por Pydantic.
- Instrumentación lista para monitoreo (logs estructurados, métricas y reportes).

## Arquitectura / Flujo
```mermaid
flowchart TD
    Scheduler[Programador / cron] --> Collectors[Collectors RSS]
    Collectors --> Parsers[Parser & Normalizador]
    Parsers --> Dedupe[Canonicalización & Dedupe]
    Dedupe --> Enrichment[Enriquecimiento NLP]
    Enrichment --> Scoring[Scoring & Explicabilidad]
    Scoring --> Reranker[Reranker & Diversidad]
    Reranker --> Storage[Persistencia (SQL, logs)]
    Storage --> Serving[APIs / Reporting]
    Storage --> Monitoring[Monitoreo & Alertas]
```
Las interfaces entre etapas se documentan en [AGENTS.md](AGENTS.md), y los contratos formales viven en `src/contracts/`.

## Instalación
### Prerrequisitos
- Python 3.10+ (probado en 3.12).
- Git.
- (Opcional) Docker 24+ para empaquetar contenedores.

### Quickstart con Makefile
```bash
make bootstrap
make test
.venv/bin/python run_collector.py --dry-run
```

### Instalación manual con `venv`
```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install --require-hashes -r requirements.lock
pip install --require-hashes -r requirements-security.lock
```

### Otras utilidades de `make`
- `make lint` / `make lint-fix` – Ruff.
- `make typecheck` – mypy sobre `src/` y `tests/`.
- `make security` – `pip-audit`, `bandit` y `trufflehog3` con `scripts/security_gate.py`.
- `make config-validate` / `make config-dump` / `make config-docs` – gestión de configuración.
- `make config-gui` – lanza el editor gráfico (requiere servidor X).
- `make clean` – elimina `.venv` y caches.

## Configuración
### Precedencia de capas
1. **Defaults** incluidos en `noticiencias.config_schema.DEFAULT_CONFIG`.
2. **Archivo TOML** (`config.toml`).
3. **Archivo `.env`** contiguo (`NOTICIENCIAS__…=valor`).
4. **Variables de entorno** con prefijo `NOTICIENCIAS__` (último gana).

Ejemplo de sobrescritura anidada:
```bash
export NOTICIENCIAS__DATABASE__DRIVER=postgresql
export NOTICIENCIAS__SCORING__MINIMUM_SCORE=0.45
export NOTICIENCIAS__COLLECTION__MAX_CONCURRENT_REQUESTS=16
```

Para inspeccionar la configuración activa:
```bash
.venv/bin/python -m noticiencias.config_manager --show-sources
.venv/bin/python -m noticiencias.config_manager --validate
.venv/bin/python -m noticiencias.config_manager --explain collection.request_timeout_seconds
```
Otros subcomandos disponibles: `--dump-defaults`, `--print-schema`, `--set clave=valor` (ver [docs/config_fields.md](docs/config_fields.md)).

### Variables críticas
| Nombre | Tipo | Default | Requerido | Descripción |
| --- | --- | --- | --- | --- |
| `collection.collection_interval_hours` | entero | 6 | Opcional | Horas entre recolecciones completas. |
| `collection.async_enabled` | bool | `false` | Opcional | Activa colector asíncrono (`httpx.AsyncClient`). |
| `collection.max_concurrent_requests` | entero | 8 | Opcional | Máximo de requests paralelos cuando hay modo async. |
| `collection.max_articles_per_source` | entero | 50 | Opcional | Recorte de artículos por fuente en cada ciclo. |
| `collection.user_agent` | texto | `NoticienciasBot/1.0 (+https://noticiencias.com)` | Recomendado | User-Agent usado en requests HTTP. |
| `rate_limiting.domain_overrides` | tabla | ver `config.toml` | Opcional | Delays específicos por host (ej. `arxiv.org = 20s`). |
| `scoring.daily_top_count` | entero | 10 | Opcional | Número de artículos destacados diarios. |
| `scoring.minimum_score` | float | 0.3 | Opcional | Umbral mínimo para publicar. |
| `scoring.source_cap_percentage` | float | 0.5 | Opcional | Máximo porcentaje de un top por fuente. |
| `scoring.topic_cap_percentage` | float | 0.6 | Opcional | Máximo porcentaje de un top por tema. |
| `paths.data_dir` | ruta | `data/` | Opcional | Raíz de artefactos (logs, DLQ, DB). |
| `database.driver` | texto | `sqlite` | Sí (implícito) | Backend soportado (`sqlite` o `postgresql`). |

### Herramientas de soporte
- **CLI**: `python -m noticiencias.config_manager` (ver ejemplos anteriores). Se puede automatizar con `make config-set KEY=app.environment=production`.
- **Editor GUI** (Tkinter): `python -m noticiencias.gui_config [ruta_config]`. En entornos sin pantalla usar `xvfb-run -a python -m noticiencias.gui_config`.

## Uso
### Recolección básica
```bash
.venv/bin/python run_collector.py --help
.venv/bin/python run_collector.py --dry-run
.venv/bin/python run_collector.py --sources nature science
.venv/bin/python run_collector.py --list-sources
.venv/bin/python run_collector.py --healthcheck --healthcheck-max-pending 50
```
Flags destacados:
- `--dry-run`: simula sin escribir en almacenamiento.
- `--sources <ids>`: filtra fuentes por ID (ver `config/sources.py`).
- `--list-sources`: imprime catálogo y termina.
- `--check-deps`: valida dependencias externas.
- `--healthcheck`: ejecuta pruebas de estado (cola, DB, ingest) con umbrales configurables.

### Ejecución programada
Usar `cron` o `systemd` apuntando a `.venv/bin/python run_collector.py`. Para entornos async habilitar `collection.async_enabled=true`.

### Ejecución en contenedor (opcional)
```bash
docker build -t noticiencias/news-collector .
docker run --rm -v $(pwd)/config.toml:/app/config.toml:ro noticiencias/news-collector --dry-run
```
Ajustar volumenes para `data/` si se desea persistencia.

## Scripts y evaluación offline
| Script | Uso | Ejemplo |
| --- | --- | --- |
| `scripts/evaluate_ranking.py` | Métricas offline (NDCG, Precision@K) | `python scripts/evaluate_ranking.py reports/runs/latest.json` |
| `scripts/reranker_distribution.py` | Comparativa de diversidad antes/después | `python scripts/reranker_distribution.py data/runs/2024-09-01.json` |
| `scripts/enrichment_sanity.py` | Sanity check de enriquecimiento (idioma, entidades, sentimiento) | `python scripts/enrichment_sanity.py data/exports/batch.json` |
| `scripts/weekly_quality_report.py` | Genera reporte semanal (monitoring.v1) | `python scripts/weekly_quality_report.py tests/data/monitoring/outage_replay.json` |
| `scripts/replay_outage.py` | Reproduce incidentes históricos con canarios | `python scripts/replay_outage.py tests/data/monitoring/outage_replay.json` |
| `scripts/healthcheck.py` | Healthcheck CLI standalone | `python scripts/healthcheck.py --max-ingest-minutes 30` |
| `scripts/run_secret_scan.py` | Ejecución directa de trufflehog3 | `python scripts/run_secret_scan.py --target .` |

Más utilidades en `scripts/` (dedupe tuning, benchmarks, perfiles de pipeline) documentadas en [docs/operations.md](docs/operations.md).

## Runbooks
- [Runbook operacional general](docs/runbook.md) – flujos de respuesta a incidentes y tableros recomendados.
- [Collector Runbook](docs/collector_runbook.md) – resolución específica para ingestión.
- [Operations Playbook](docs/operations.md) – tareas recurrentes (backfills, rotación de llaves).
- [Performance baselines](docs/performance_baselines.md) – objetivos por etapa.
- [FAQ detallado](docs/faq.md) – preguntas frecuentes ampliadas.

## Datos de entrada/salida
- **Entradas**: feeds RSS/Atom definidos en `config/sources.py`; límites de rate se configuran en `config.toml` (`rate_limiting.*`).
- **Salidas**:
  - Base de datos SQL (`database.driver` + `database.path/host`). Por defecto `data/news.db` (SQLite).
  - Logs estructurados en `data/logs/`.
  - DLQ y artefactos intermedios en `data/dlq/`.
  - Reportes y cobertura en `reports/` (`reports/coverage/`, `reports/security/`).
- **Formato de monitoreo**: ver [docs/common_output_format.md](docs/common_output_format.md) (schema `monitoring.v1`).

## Estructura del proyecto
```
noticiencias_news_collector/
├── run_collector.py          # CLI principal y orquestador
├── config/                   # Versionado, fuentes, settings auxiliares
├── config.toml               # Configuración por defecto
├── noticiencias/             # Paquete con gestores de configuración/GUI
├── src/                      # Código de la aplicación (collectors, enrichment, scoring, etc.)
├── scripts/                  # Herramientas operativas y evaluaciones offline
├── tests/                    # Suite de pruebas (unitarias, perf, e2e)
├── docs/                     # Manuales, runbooks, especificaciones
├── Makefile                  # Automatización de tareas locales
└── Dockerfile                # Imagen base para despliegues
```

## Pruebas
- `make test` ejecuta `pytest` con cobertura (`reports/coverage/`).
- Marcadores: `-m "e2e"`, `-m "perf"` para suites específicas.
- Para linting: `make lint`; tipos: `make typecheck`.

_Nota_: la cobertura actual ronda 69%. Nuevos módulos deben venir con pruebas que acerquen el objetivo interno (≥80%).

## CI/CD
Workflows en `.github/workflows/`:
- `ci.yml`: lint, tests y seguridad en pushes/PRs.
- `security.yml`: escaneos dedicados (bandit, trufflehog, pip-audit).
- `dependency-lock-check.yml`: valida sincronía de lockfiles.
- `manual-lock-sync.yml`: job manual para refrescar `requirements.lock`.
- `release.yml`: empaquetado y publicación (ver [release checklist](docs/release-checklist.md)).
- `sync-master.yml`: sincronización con ramas ascendentes.

## Performance y límites conocidos
- Objetivos de latencia y throughput en [docs/performance_baselines.md](docs/performance_baselines.md).
- Rate limiting configurable por dominio (`rate_limiting.domain_overrides`).
- Modo async exige `collection.async_enabled=true` y ajustar `max_concurrent_requests` para no exceder límites de origen.
- Scoring penaliza dominancia por fuente/tema según `scoring.source_cap_percentage` y `scoring.topic_cap_percentage`.

## Seguridad
- Secrets siempre via variables de entorno (`NOTICIENCIAS__DATABASE__PASSWORD`, etc.).
- Ejecutar `make security` antes de merges críticos.
- `scripts/run_secret_scan.py` usa `trufflehog3` con patrones definidos en `tools/placeholder_patterns.yml`.
- Revisar [docs/security.md](docs/security.md) para políticas de acceso y rotación.

## Troubleshooting & FAQ
- Sección rápida en [docs/faq.md](docs/faq.md).
- Healthcheck manual: `python scripts/healthcheck.py --max-pending 100`.
- Reprocesar duplicados: `python scripts/recluster_articles.py --window 48h` (ver runbook del colector).
- Para errores de GUI en servidores sin display, usar `xvfb-run -a python -m noticiencias.gui_config`.

## Roadmap y limitaciones
- `CHANGELOG.md` y [docs/release_notes.md](docs/release_notes.md) documentan hitos.
- Limitaciones actuales: cobertura <80%, solo SQLite/PostgreSQL soportados, GUI requiere entorno gráfico.
- Próximos pasos sugeridos: habilitar colas externas (Redis/Kafka), mejorar cobertura en módulos de collectors/scoring.

## Contribución
- Revisar [CONTRIBUTING.md](CONTRIBUTING.md) y guías de estilo (PEP-8, tipado estricto, pruebas obligatorias).
- Usar ramas feature (`feature/<tema>`), crear PRs con descripción y enlaces a runbooks relevantes.
- Ejecutar `make lint typecheck test security` antes de solicitar revisión.

## Licencia y créditos
Falta: archivo de licencia. Confirmar con el equipo legal u operations antes de distribuir externamente.

Créditos principales: equipo Noticiencias (ver autores en commits y `docs/release_notes.md`).

## Preguntas abiertas
- Licencia del proyecto: consultar a responsables en `#ops-legal` y añadir `LICENSE` al repositorio.
