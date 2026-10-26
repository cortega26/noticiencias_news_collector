# Plan 196 — herramientas de desarrollo: xdist, import-linter, respx, deptry, time-machine

## Objetivo

Agregar cinco herramientas de desarrollo al extra `test` (y por tanto a
`requirements-security.lock`, con hashes), sin tocar dependencias de runtime ni
el comportamiento del colector.

Criterios de aceptación:

- `pytest-xdist`, `respx`, `time-machine`, `import-linter` y `deptry` están en
  `[project.optional-dependencies].test` y fijados con hash en
  `requirements-security.lock`; `sync_lockfiles.py --check` queda limpio y
  `requirements.lock` (runtime) no cambia.
- `make test-parallel` ejecuta el mismo alcance que `make test` con `-n auto`.
- `make lint-imports` aplica un contrato `forbidden`: scoring, taxonomy y
  editorial no importan directamente clientes de red (`requests`, `httpx`,
  `urllib3`, `aiohttp`, `feedparser`, `playwright`, `scrapling`) ni
  `news_collector.collectors`/`news_collector.serving`. Forma parte de
  `verify-ci`.
- `make deps-check` ejecuta deptry en modo consultivo (no bloquea CI).
- `make test-timeshift` usa `time-machine` del lock en lugar de instalarlo sin
  fijar.

## Decisiones

- **Contrato solo directo (`allow_indirect_imports = true`).**
  `news_collector/__init__.py` importa de forma anticipada collectors, serving y
  storage, así que todo submódulo alcanza la red transitivamente. Quitar esa
  carga cambia la API pública del paquete y queda fuera de este plan.
- **`news_collector/validation` queda fuera del contrato.** Es un paquete
  namespace (sin `__init__.py`) y grimp no lo resuelve.
- **El target usa el ejecutable `lint-imports`.** En import-linter 2.6 (la
  versión del lock), `python -m importlinter.cli` sale con 0 sin ejecutar nada.
- **deptry es consultivo.** Sus hallazgos actuales (abajo) requieren decisiones
  del propietario y no deben convertirse en un gate rojo.

## Verificación

| Comprobación | Comando | Resultado esperado |
| --- | --- | --- |
| Locks frescos | `python scripts/sync_lockfiles.py --check` | sin cambios |
| Paridad del venv | `python scripts/check_lock_parity.py` | OK |
| Contrato se cumple | `make lint-imports` | `1 kept, 0 broken` |
| Contrato detecta violación | agregar `import requests` en `news_collector/scoring/` y ejecutar `make lint-imports` | código ≠ 0 |
| Humo respx/time-machine/contrato | `pytest tests/unit/tooling -q --no-cov` | 3 passed |
| Suite en paralelo | `make test-parallel` | 4465 passed; solo los 20 fallos preexistentes |
| Lint y docs | `make lint`, `make docs-check` | verdes |

## Hallazgos registrados (sin corregir en este plan)

- **20 tests fallan ya en `main`**, en serie y en paralelo:
  `tests/unit/config/test_live_refresh.py` (9),
  `tests/unit/refinery/test_save_toml_config.py` (6),
  `tests/test_config_manager.py` (3) y `tests/test_cli_config.py` (2). La causa es
  `scoring.weights` en la fixture, que no suma 1.0.
- **deptry (`make deps-check`)**: `scikit-learn` y `numpy` están declaradas sin
  uso directo; `spacy` (`enrichment/nlp_stack.py`) y `psutil`
  (`utils/logger.py`) se importan sin estar declaradas (revisar si son
  opcionales con guardia); `tomli` se importa como transitiva;
  `scripts/score_delta.py`, `scripts/weekly_quality_report.py` y
  `tools/perf/profile_collectors.py` importan módulos inexistentes (`src`,
  `monitoring`, `config`).

## Todo

- [x] Agregar las cinco herramientas al extra `test`
- [x] Configurar `[tool.importlinter]` y `[tool.deptry]` en `pyproject.toml`
- [x] Targets `test-parallel`, `lint-imports` (en `verify-ci`) y `deps-check`
- [x] `test-timeshift` sin `pip install` sin fijar
- [x] Regenerar locks; verificar `--check` y paridad
- [x] Probar que el contrato detecta una violación
- [x] Tests de humo en `tests/unit/tooling/`
- [x] PR y CI (#396)

## Cierre (2026-10-26)

Hallazgos registrados arriba, resueltos en PRs posteriores:

- Los 20 fallos solo ocurrían en local: el `.env` del repo se filtraba en las
  configs temporales de los tests. Corregido en #397
  (`NOTICIENCIAS_DEFAULT_ENV_PATH`).
- deptry: `scikit-learn`/`numpy` quitadas y `score_delta.py`/
  `weekly_quality_report.py` reparados en #398;
  `tools/perf/profile_collectors.py` eliminado en #399. `spacy` y `psutil` se
  mantienen como opcionales con guardia de `ImportError`.
