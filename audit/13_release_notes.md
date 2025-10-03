# Phase 13 — Release Notes

## Overview
- **Version:** 1.1.0 (2025-10-03)
- **Highlights:** Consolidated documentation with architecture diagrams and runbook cross-references, expanded performance harnesses for collectors, and formalized release automation with reproducible tooling.

## Grouped Updates
### Docs
- README incorpora un diagrama Mermaid del flujo de ingesta y referencias explícitas a contratos y runbooks operativos para mantener alineadas las áreas de datos y operaciones.【F:README.md†L1-L27】【F:README.md†L149-L188】
- La checklist de releases guía validaciones de CI, seguridad y publicación de imágenes, asegurando trazabilidad en cada entrega.【F:docs/release-checklist.md†L1-L31】

### Configuración
- El módulo `config.version` centraliza la lectura de `VERSION`, exponiendo metadatos inmutables reutilizables por CLI y tooling.【F:config/version.py†L1-L54】
- El inicializador de `config` publica explícitamente los atributos disponibles por módulo, simplificando introspección y auto-documentación de parámetros.【F:config/__init__.py†L1-L92】

### Pruebas
- Suite de regresión incluye pruebas de rendimiento determinísticas para comparar colectores sync vs async sobre fixtures JSONL, preservando garantías de throughput.【F:tests/perf/test_async_collector_perf.py†L1-L61】
- Cobertura funcional de canonicalización, GUI de configuración y CLI fue alineada con la guía de auditoría mediante casos detallados en `tests/` (e.g., `test_url_canonicalizer.py`, `test_runner_cli.py`, `test_gui_config_persistence.py`).【F:tests/test_url_canonicalizer.py†L1-L112】【F:tests/e2e/test_runner_cli.py†L1-L124】【F:tests/gui/test_gui_config_persistence.py†L1-L121】

### Seguridad
- `scripts/run_secret_scan.py` y `scripts/security_gate.py` quedan listos para integraciones automatizadas; en esta fase se ejecutaron bandit, gitleaks y pip-audit para documentar el estado de riesgos previos al tag.【F:scripts/security_gate.py†L1-L142】【F:scripts/run_secret_scan.py†L1-L118】

### Performance
- Harness de replay (`src/perf/load_replay.py`) y perfilador de colectores (`tools/perf/profile_collectors.py`) habilitan comparativas reproducibles, con métricas documentadas en `audit/09_perf_findings.md`.【F:src/perf/load_replay.py†L1-L233】【F:tools/perf/profile_collectors.py†L1-L147】【F:audit/09_perf_findings.md†L1-L53】

### CI / Release Automation
- El Makefile expone el objetivo `bump-version` y scripts auxiliares (`scripts/bump_version.py`, `scripts/update_changelog.py`) para gestionar SemVer y notas automatizadas.【F:Makefile†L1-L190】【F:scripts/bump_version.py†L1-L141】【F:scripts/update_changelog.py†L1-L164】
- Pipelines de documentación (`docs/`, `README`) enlazan a healthchecks y FAQ para reducir el tiempo de resolución frente a incidentes.【F:README.md†L149-L222】

## Verification Summary
| Check | Command | Status / Notes |
| --- | --- | --- |
| Dependencies | `pip install --require-hashes -r requirements.lock` | ✅ Ya instaladas; solo se ajustó `typing-inspection` a la versión bloqueada.【66d0e5†L1-L57】 |
| Lint | `ruff check src tests` | ✅ Sin hallazgos.【7ead09†L1-L2】 |
| Formatting | `black --check .` | ✅ Tras aplicar `black`, no quedaron archivos pendientes.【82dc55†L1-L2】 |
| Imports | `isort --check-only src tests scripts` | ❌ Falla por deuda previa en múltiples módulos; se documenta para seguimiento.【d74197†L1-L26】 |
| Type checking | `mypy src` | ✅ Solo nota sobre funciones sin tipado estricto; sin errores.【e54bb8†L1-L4】 |
| Tests + cobertura | `pytest --cov=src` | ✅ 145 pruebas pasaron; cobertura total 72% (bajo el objetivo ≥80%, requiere plan de incremento).【177399†L1-L52】 |
| SAST | `bandit -ll -r src` | ✅ Sin issues de severidad ≥Medium; 7 hallazgos Low conocidos.【69f427†L1-L23】 |
| Secret scan | `gitleaks detect --no-git --source .` | ⚠️ 1 falso positivo en `audit/03_config_matrix.md` (literal “KEY” en documentación).【711d70†L1-L2】【b8ec3f†L1-L25】 |
| Vulnerabilidades | `pip-audit` | ⚠️ Reporta CVE para `pip==25.2`; no existe versión parcheada, se mitiga ejecutando en entornos confinados.【a280cc†L1-L4】【b66d6e†L1-L6】 |

## Migration / Compatibility Notes
- No se modificaron claves de configuración ni esquemas; no se requieren migraciones.
- Mantener monitoreo de cobertura (<80%) y deuda de `isort` antes de etiquetar la versión estable.

## Evidence Archive
- Resultados crudos de comandos incluidos en `reports/` (sin cambios) y en los logs citados arriba para trazabilidad.
