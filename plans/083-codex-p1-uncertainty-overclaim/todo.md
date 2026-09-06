# TODO — Plan 083

- [x] Spec (finding + causa raíz + diseño: detector, no reescritor)
- [x] `find_capability_overclaims` + `find_unvalidated_capability_claims` en `editorial/uncertainty.py`
- [x] Hook (solo `logger.warning`) en el ensamblaje de frontmatter de `ai_editor.py` tras `resolve_uncertainty_counterweight`
- [x] Tests unitarios (caso Codex verbatim + oración compuesta + matriz de texto seguro + no-op sin contrapeso)
- [x] Suite `tests/unit/editorial/` en verde (306 passed, 1 skipped)
- [x] `ruff` + `black` + `isort` + `mypy` en los archivos tocados
- [ ] Commit + push + PR (+ vigilar CI)
- [x] Fix de la instancia del PR #153 entregado como commit de contenido en la rama del PR (why_it_matters[1] reformulado a prospectivo)
