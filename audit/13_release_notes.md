# Phase 13 — Release Notes

## Overview
- **Version:** 1.2.0 (2025-10-04)
- **Highlights:** Refuerzo del caché HTTP en colectores RSS, cobertura integral para precedencia de configuración y CLI, además de pipelines de CI acelerados con automatización de inventario.

## Grouped Updates
### Docs
- README documenta la matriz de precedencia (`defaults → config.toml → .env → entorno`) con ejemplos concretos, facilitando alineación entre CLI y GUI.【F:README.md†L102-L139】
- La FAQ incorpora pasos para diagnosticar validaciones fallidas al guardar desde la GUI, apuntando a CLI y runbooks comunes.【F:docs/faq.md†L17-L37】
- Se añadió `docs/ci.md` con la tabla de checks requeridos, estrategias de caché y el flujo semanal de inventario automatizado.【F:docs/ci.md†L1-L44】【F:docs/ci.md†L46-L74】

### Configuración
- `load_config` respeta explícitamente el mapeo de entorno inyectado en pruebas/CLI en lugar de leer siempre `os.environ`, evitando efectos secundarios en precedencia.【F:noticiencias/config_manager.py†L332-L339】
- El editor GUI propaga `ConfigError` como `SystemExit` encadenado, mejorando rastreabilidad cuando la validación falla desde la interfaz gráfica.【F:noticiencias/gui_config.py†L557-L563】

### Pruebas
- La matriz parametrizada en `tests/e2e/test_config_precedence.py` cubre todas las combinaciones de defaults, archivo, `.env` y entorno de proceso, validando también metadatos de procedencia.【F:tests/e2e/test_config_precedence.py†L1-L92】【F:tests/e2e/test_config_precedence.py†L94-L138】
- Los tests E2E del CLI (`tests/e2e/test_runner_cli.py`) ahora verifican logging estructurado para inicialización, healthcheck y rutas de error.【F:tests/e2e/test_runner_cli.py†L1-L120】【F:tests/e2e/test_runner_cli.py†L212-L272】
- Nuevas pruebas del colector sincronizado/asíncrono ejercen encabezados condicionales, hash de contenido y backoff de 429 para prevenir descargas redundantes.【F:tests/collectors/test_http_cache_behavior.py†L1-L120】【F:tests/collectors/test_http_cache_behavior.py†L122-L220】

### Seguridad
- El workflow `security` reutiliza cachés de dependencias y sube reportes estructurados para Bandit, Gitleaks y pip-audit, aplicando `scripts/security_gate.py` como guardia severidad ≥HIGH.【F:.github/workflows/security.yml†L1-L64】【F:.github/workflows/security.yml†L66-L118】
- La configuración de Gitleaks amplía allowlists para fixtures y añade reglas genéricas de API keys, reduciendo falsos positivos durante auditorías.【F:.gitleaks.toml†L1-L24】

### Performance
- Los colectores RSS sincronizado y asíncrono reutilizan ETag/Last-Modified y comparan `content_hash` para omitir feeds sin cambios, registrando métricas al saltar descargas.【F:src/collectors/rss_collector.py†L392-L459】【F:src/collectors/rss_collector.py†L484-L558】
- `AsyncRSSCollector` comparte el mismo caché de metadatos y encabezados condicionales, asegurando coherencia con el colector base durante replays de alto volumen.【F:src/collectors/async_rss_collector.py†L96-L138】【F:src/collectors/async_rss_collector.py†L180-L238】

### CI / Release Automation
- `ci.yml` paraleliza jobs, ratchea cobertura y aplica caché en `setup-python`, mientras que `docs.yml` y `security.yml` heredan concurrencia para evitar ejecuciones obsoletas.【F:.github/workflows/ci.yml†L1-L120】【F:.github/workflows/docs.yml†L1-L46】
- `audit-inventory-weekly.yml` ejecuta `scripts/generate_inventory.py` para comparar snapshots sanitizados y adjuntar artefactos cuando hay drift.【F:.github/workflows/audit-inventory-weekly.yml†L1-L88】
- El script `scripts/generate_inventory.py` genera inventario ordenado con índices de funciones/clases, diffs JSON y preguntas abiertas detectadas automáticamente.【F:scripts/generate_inventory.py†L1-L120】【F:scripts/generate_inventory.py†L188-L274】

## Verification Summary
| Check | Command | Status / Notes |
| --- | --- | --- |
| Dependencies | `pip install --require-hashes -r requirements.lock` | ✅ Entorno actualizado; se revirtió `typing-inspection` a la versión fijada.【1186d3†L1-L58】 |
| Lint | `ruff check src tests` | ✅ Sin hallazgos.【4dc2d6†L1-L3】 |
| Formatting | `black --check .` | ❌ 5 archivos preexistentes requieren formato; no tocados en esta fase para evitar ruido masivo.【16aac0†L1-L8】 |
| Imports | `isort --check-only src tests scripts` | ❌ Deuda histórica en suites de pruebas y scripts; se documenta para seguimiento.【f9847b†L1-L32】 |
| Type checking | `mypy src` | ✅ Sin errores; solo aviso sobre funciones sin tipado estricto.【0ec715†L1-L4】 |
| Tests + cobertura | `pytest --cov=src` | ❌ Falla `test_async_collector_outperforms_sync` por regresión de performance y cobertura total 67.44% < 80%.【6ba392†L1-L80】 |
| SAST | `bandit -ll -r src` | ✅ Sin issues ≥Medium; se registran 7 Low conocidos.【1c0f82†L1-L24】 |
| Secret scan | `gitleaks detect --no-git --source .` | ⚠️ 1 falso positivo en `audit/03_config_matrix.md` (literal “KEY” en documentación).【9f5815†L1-L3】【900abc†L1-L21】 |
| Vulnerabilidades | `pip-audit` | ⚠️ Reporta GHSA-4xh5-x5gv-qwph para `pip==25.2`; sin parche publicado, se mitiga en entornos confinados.【843564†L1-L4】 |

## Migration / Compatibility Notes
- No se introdujeron nuevas claves de configuración; no se requieren migraciones.
- Las mejoras de caché dependen de `content_hash` almacenado en la base, pero conservan compatibilidad con registros anteriores.

## Evidence Archive
- Resultados crudos de comandos y reportes exportados en `reports/` y adjuntados en la sección de verificación tras su ejecución.
