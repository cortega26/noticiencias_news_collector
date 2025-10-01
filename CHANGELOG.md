# Changelog

All notable changes to this project will be documented in this file. The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]
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
