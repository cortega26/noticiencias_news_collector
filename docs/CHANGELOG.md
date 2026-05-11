# Changelog

All notable changes to this project will be documented in this file. The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

### Added

- Composite action `.github/actions/setup-python-env/` consolidates the
  setup-python → cache → bootstrap pattern used across CI workflows.

### Changed

- **CI workflow consolidation**: `ci.yml`, `e2e.yml`, `daily_collector.yml`,
  `source_reliability.yml`, `live-source-drift.yml`, and `publication-smoke.yml`
  now use the shared composite action for Python environment setup, eliminating
  ~170 lines of duplicated step definitions across 12+ CI jobs.
- **Removed `main.py`**: The deprecated CLI entrypoint (previously a thin wrapper
  around `scripts/run_collector.py`) has been deleted. All documentation references
  updated across 7 files. `tests/test_error_handling.py` removed with it.
- **Documentation alignment**: `docs/INDEX.md` ops runbook pointer corrected from
  legacy `ops/RUNBOOK.md` to current `runbook.md`. `docs/security.md` bandit
  command no longer references removed `main.py`.

## [1.3.0] - 2026-01-24

### Added

- **Headless Collector**: Nueva implementación basada en Playwright para recolectar contenido de sitios dinámicos o protegidos (Nature, Science, etc.).
- Soporte para selectores CSS personalizados en configuración de fuentes headless.
- Dependencia `playwright` añadida a `requirements.txt` y lockfiles.
- Mocking robusto de `health_tracker` en tests de parsers headless.

### Changed

- **Validación de Contenido**: Reducido el umbral `min_content_length` a 500 caracteres (previo 1000) para admitir artículos breves legítimos.
- **Correcciones de Estabilidad**:
  - Solucionado bug donde las fuentes headless no reportaban métricas en la auditoría final.
  - Corregido error de importación `pytest-asyncio` pineando la versión compatible.
  - Resolución masiva de errores de linting y formateo (Black/Isort/Ruff) en todo el proyecto.
- **Mejoras en Tests**:
  - Fix en `test_headless_parser.py` para evitar `AttributeError` en health tracker.
  - Sincronización de `requirements.lock` y `requirements-security.lock`.

## [1.2.0] - 2025-10-04

### Added

- README y FAQ documentan precedencia de configuración y troubleshooting GUI, complementadas por la suite parametrizada de `tests/e2e/test_config_precedence.py` (#123, #125).
- `tests/e2e/test_runner_cli.py` amplía la cobertura del CLI con validaciones de logging estructurado y rutas de error críticas (#124).
- Automatización de inventario semanal vía `audit-inventory-weekly.yml` y `scripts/generate_inventory.py`, incluyendo diffs y artefactos para auditoría (#127).

### Changed

- `noticiencias.config_manager.load_config` respeta entornos inyectados y la GUI encadena `SystemExit` para exponer causas exactas al usuario (#123, #125).
- Los colectores RSS y Async aplican encabezados condicionales y hash de contenido para evitar descargas redundantes y mejorar telemetría (#126).
- Los workflows de CI y seguridad aplican cachés de dependencias, ratchets de cobertura y publicación de reportes estructurados para Bandit/Gitleaks/pip-audit (#127).

## [1.1.0] - 2025-10-03

### Added

- Arquitectura Mermaid en el README con enlaces a contratos compartidos para reforzar decisiones del pipeline.
- Preguntas frecuentes de troubleshooting cubriendo bloqueos de BD, límites de tasa y modelos faltantes.
- Referencias cruzadas a los runbooks y lineamientos de logging en la documentación operativa.
- Módulo único de versionado con script/objetivo `make bump-version` para subir SemVer de forma segura.
- Checklist de release que valida CI, budgets de performance/seguridad, documentación y bootstrap reproducible.
- Automatización de changelog al crear tags que también genera borradores de GitHub Releases.
- Dockerfile y job opcional de build que empaqueta la app como `noticiencias/collector:<fecha>.<sha>` con instrucciones de ejecución.

### Changed

- Guía de contribución actualizada con estándares de código, convenciones de commits y proceso para refrescar fixtures tras la auditoría.
- `pyproject.toml` ahora lee la versión directamente del módulo de configuración para evitar fuentes duplicadas.
