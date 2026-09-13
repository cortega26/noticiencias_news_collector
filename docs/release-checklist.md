# ✅ Release Checklist

Esta lista asegura que cada release del News Collector cumple los contratos operativos definidos en `docs/AGENTS.md`. Marca cada elemento antes de crear un tag `vX.Y.Z`.

## 1. Salud de CI
- [ ] Los checks aplicables a la revisión de release están en verde; consultar `docs/ci.md` para workflows separados y límites de los targets.
- [ ] No hay regresiones abiertas en la matriz de pruebas manuales.

## 2. Presupuestos de Performance y Seguridad
- [ ] Las pruebas de rendimiento aplicables se ejecutaron y pasaron realmente; `make perf` puede ocultar fallos. Ver `docs/performance_baselines.md`.
- [ ] `make security` está libre de hallazgos HIGH y el gate (`scripts/security_gate.py`) marca estado `pass`.

## 3. Documentación y Comunicación
- [ ] `CHANGELOG.md` refleja los cambios planeados para la versión.
- [ ] Documentación en `docs/` y `README.md` está actualizada con nuevos flags, dependencias o flujos.
- [ ] Las notas de release generadas automáticamente fueron revisadas y editadas si es necesario.

## 4. Verificación Operacional
- [ ] `make bump-version PART=<major|minor|patch>` o `make bump-version VERSION=X.Y.Z` ejecutado y versionado commit.
- [ ] `make bootstrap` se ejecuta exitosamente en un entorno limpio (incluye `requirements.lock` + `requirements-security.lock`).
- [ ] `.venv/bin/python scripts/run_collector.py --dry-run` produce resultados consistentes y sin errores.

## 5. Artefactos y Deploy
- [ ] El workflow `Release` terminó en verde, creó el borrador de GitHub Release y actualizó el changelog automáticamente.
- [ ] El job `Build release container image` generó el artefacto `noticiencias/collector:<fecha>.<sha>` y se revisaron las instrucciones de ejecución incluidas.
- [ ] Se registró la fecha de despliegue en el log operativo.

> Sugerencia: Guarda esta checklist como parte del issue o ticket de release para trazabilidad.
