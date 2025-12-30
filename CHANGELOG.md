# Changelog

All notable changes to this project will be documented in this file. The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]
### Added
- No hay cambios nuevos desde la versión 1.2.0.

### Changed
- No hay cambios nuevos desde la versión 1.2.0.

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
