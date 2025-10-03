# Phase 8 — Reproducible Builds & Supply Chain (PEV)

## Summary
- Consolidamos los locks `requirements.lock` y `requirements-security.lock` como única fuente de verdad para dependencias runtime y herramientas de seguridad.
- Añadimos objetivos de Make reproducibles (`type`, `audit`, `build`) y actualizamos los workflows de CI para usarlos como puertas estandarizadas.
- Configuramos Dependabot en modo `lockfile-only` para paches semanales de pip y GitHub Actions sin romper los pines existentes.

## Decisions & Rationale
| Área | Decisión | Justificación |
| --- | --- | --- |
| Gestión de dependencias | Mantener `requirements.lock` (runtime) + `requirements-security.lock` (escáneres) generados con `pip-compile`. | Ya existen locks con hashes; evita duplicar especificaciones en `pyproject.toml` y simplifica auditorías (R1, R2). |
| Automatización | Alias `make type` y `make audit`; nuevo `make build` basado en `pip wheel`. | Unifica la nomenclatura pedida (bootstrap, lint, type, test, audit, build) y produce artefactos deterministas sin dependencias adicionales (R1, R6). |
| Actualizaciones | Dependabot `lockfile-only` para pip + job semanal de GitHub Actions. | Garantiza parches controlados respetando los pines y mantiene infraestructura CI al día (R2, R6). |

## Implementation Notes
- README documenta la estrategia de locks y pasos para regenerarlos, junto con la actualización de Roadmap (Fase 8 marcada como completada).
- Workflows `ci.yml` y `security.yml` ahora invocan `make type` y `make audit` para compartir lógica con desarrollo local.
- `make build` limpia `dist/` antes de crear un wheel con dependencias congeladas y se apoyó en `setup.py` minimalista + `pyproject` para resolver la versión vía archivo `VERSION` (evita ejecuciones interactivas durante el build).
- El binario de seguridad `trufflehog3` pincha `Jinja2==3.1.4`; se instaló la versión corregida `3.1.6` tras la instalación y se documentó el riesgo hasta que upstream libere un parche.

## Verification
| Comando | Propósito | Resultado |
| --- | --- | --- |
| `make bootstrap` | Instalación desde cero con hashes. | ✅ | 
| `make lint` | Validación Ruff. | ✅ |
| `make type` | Tipado estricto en módulos cambiados. | ✅ |
| `make test` | Suite de pytest con cobertura. | ✅ |
| `make build` | Generación de wheel determinista. | ✅ |
| `pip-audit -r requirements.lock` | Escaneo de dependencias runtime. | ✅ |
| `pip-audit -r requirements-security.lock` | Escaneo de herramientas de seguridad. | ⚠️ — `trufflehog3` exige `Jinja2==3.1.4`; se instaló 3.1.6 manualmente y se dejó constancia del conflicto. |
| `bandit` / `security_gate.py` | SAST en `src/` y scripts. | ✅ |
| `scripts/run_secret_scan.py` + `security_gate.py` | Trufflehog3 (alto) sin hallazgos. | ✅ |

## Follow-ups
- Monitorear los primeros PRs de Dependabot para confirmar que `lockfile-only` respeta la política de versiones y no requiere cambios manuales adicionales.
