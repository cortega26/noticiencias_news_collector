# Documentación — Changelog

## 2025-10-03

### Actualizado
- README.md: Quickstart actualizado con `make lint typecheck test`, `make security` y descripciones alineadas al flujo de bootstrap verificado.
- README.md: Tabla de configuración extendida con defaults verificados desde `noticiencias.config_schema`.
- CI: Nuevo workflow `docs.yml` con validación automática de enlaces usando `linkchecker` en cambios de documentación.

### Comandos validados
- `python run_collector.py --help`
- `python -m noticiencias.config_manager --help`
- `python -m scripts.healthcheck --help`

