# ✅ Release Checklist

Esta lista asegura que cada release del News Collector cumple los contratos operativos definidos en `AGENTS.md#9`. Marca cada elemento antes de crear un tag `vX.Y.Z`.

## 1. Salud de CI
- [ ] Todas las ejecuciones de `CI` en GitHub Actions están en verde (lint, typecheck, test, e2e, perf, security).
- [ ] No hay regresiones abiertas en la matriz de pruebas manuales.

## 2. Presupuestos de Performance y Seguridad
- [ ] Los reportes en `reports/perf` están dentro de los budgets publicados en el runbook.
- [ ] `make security` está libre de hallazgos HIGH y el gate (`scripts/security_gate.py`) marca estado `pass`.

## 3. Documentación y Comunicación
- [ ] `CHANGELOG.md` refleja los cambios planeados para la versión.
- [ ] Documentación en `docs/` y `README.md` está actualizada con nuevos flags, dependencias o flujos.
- [ ] Las notas de release generadas automáticamente fueron revisadas y editadas si es necesario.

## 4. Verificación Operacional
- [ ] `make bump-version PART=<major|minor|patch>` o `make bump-version VERSION=X.Y.Z` ejecutado y versionado commit.
- [ ] `make bootstrap` se ejecuta exitosamente en un entorno limpio (incluye `requirements.lock` + `requirements-security.lock`).
- [ ] `python run_collector.py --dry-run` produce resultados consistentes y sin errores.

## 5. Artefactos y Deploy
- [ ] El workflow `Release` terminó en verde, creó el borrador de GitHub Release y actualizó el changelog automáticamente.
- [ ] El job opcional `Build release container` generó el artefacto `noticiencias/collector:<fecha>.<sha>` y se revisaron las instrucciones de ejecución incluidas.
- [ ] Se registró la fecha de despliegue en el log operativo.

> Sugerencia: Guarda esta checklist como parte del issue o ticket de release para trazabilidad.
