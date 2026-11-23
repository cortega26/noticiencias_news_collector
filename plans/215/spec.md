# Plan 215 · Recuperar los gates de dependencias del Collector

**Base** `ffebfc9b3c8ff91cd001b3e2cc1c085ab6acbfc6` · 2026-11-22 · **Prioridad** P1 · **Riesgo** medio · **Esfuerzo** M · **Hallazgo** C01

## Resultado

Los lockfiles con hashes y los dos lockfiles npm pasan los gates reales con dependencias parcheadas. El recolector sigue interpretando el HTML de los fixtures y el replay conserva su contrato y control negativo.

## Estado y alcance

- `requirements.lock:1259`, `requirements-refinery.lock:1801`, `requirements-security.lock:2011` fijan Soup Sieve 2.9.1, y `requirements-semgrep.lock:1997` fija 3.0.3. El bloqueo del runtime se reprodujo con el gate real del Collector. La versión corregida para el aviso alto más restrictivo revisado es 4.0.0. Verificar la compatibilidad con Beautiful Soup 4.15.0 y los selectores de colección. El lock autónomo de Semgrep reportó además avisos en `mcp`, `opentelemetry-api` y `wcmatch`. Separar sus resoluciones y validar el arranque del scanner antes de cambiar versiones. [Aviso del mantenedor](https://github.com/advisories/GHSA-mmhr-3c5m-f64f)
- `apps/admin/package-lock.json:2974` fija Astro 7.4.0. El aviso moderado se corrige desde 7.4.7. El Admin es estático y carece del adaptador descrito, pero `.github/workflows/quality.yml:36–39` bloquea desde severidad baja. `tools/editorial_eval/package-lock.json` tiene múltiples avisos transitivos, incluido Mongoose 9.x por debajo de 9.11.4. Auditar resoluciones compatibles antes de aceptar un cambio de rango de Promptfoo. [Astro](https://github.com/advisories/GHSA-r3h5-4585-7x3w), [Mongoose](https://github.com/advisories/GHSA-gg4r-jv3p-qx3c)
- Alcance de cambios. Los cuatro `requirements*.lock`, las entradas de resolución Python que use `scripts/sync_lockfiles.py` si son necesarias, `apps/admin/package*.json`, `tools/editorial_eval/package*.json` y la nota activa de dependencias en `docs/ci.md`. Restringir cambios en configuración de replay o casos de prueba a una incompatibilidad reproducida. El `uv.lock` local sin seguimiento no pertenece al flujo de CI.

## Decisiones y verificación

1. Trabajar sobre un checkout aislado y comparar los locks y el script de generación contra la base. Ejecutar los cuatro `pip-audit --disable-pip --require-hashes -r <lock>` y los dos `npm audit --package-lock-only --include=dev --audit-level=low`. Registrar versiones, alcance y salida. Los registros externos pueden haber cambiado.
2. Regenerar Python con el mismo generador utilizado por `.github/workflows/manual-lock-sync.yml`, conservando hashes y restricciones cruzadas. Confirmar `python scripts/sync_lockfiles.py --check` y `make lock-parity-check` con entornos limpios. Validar la colección HTML con `make test` y los casos `tests/unit/collectors/test_html_collector*.py`.
3. Resolver npm en los dos paquetes sin bajar sus umbrales ni añadir excepciones. Confirmar `npm ci` y `npm audit --include=dev --audit-level=low` en ambos. Para Admin, ejecutar `npm test`, `npm run check`, `npm run contracts:check` y `npm run build`. Para Promptfoo, ejecutar `make editorial-eval-replay` con sus fixtures offline y el control negativo esperado.
4. Ejecutar `make quality`, `make security-dev` y `make docs-check`, volver a consultar los seis lockfiles y verificar por separado que Semgrep inicia y ejecuta el gate documentado. Revisar el diff de versiones y registrar qué paquetes justifican cambios secundarios. La línea base de auditoría incluye 97 tests de Admin, typecheck y build estático, además de los bloqueos reproducidos por los scanners. Los gates tras actualizar dependencias son aceptación pendiente.

Detener la actualización si el único camino disponible altera las comparaciones del replay, el contrato del Admin o el parseo HTML. Documentar la incompatibilidad y volver a medir el alcance. Cerrar con evidencia de CI del SHA entregado y actualizar la fila 215.
