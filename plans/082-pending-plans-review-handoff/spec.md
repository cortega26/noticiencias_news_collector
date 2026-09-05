# Plan 082 — Handoff: revisión y reconciliación de planes pendientes

> **Qué es esto:** instrucción para un agente con más contexto. NO es
> autorización para implementar cambios de código, desplegar, publicar
> artículos ni tocar datos de producción. El entregable es revisión +
> reconciliación documental de los planes pendientes. La implementación
> de lo que surja se asigna por separado.

## 1. Objetivo

Dejar un estado verificado y reconciliado de todos los planes no
archivados (`plans/048/`, `plans/060/`, `plans/080/`, `plans/081/`):
qué está realmente pendiente, qué es drift (documentación que ya no
describe el código), y qué decisiones requieren al operador. Al terminar,
cada plan pendiente debe tener spec/todo/ledger coherentes entre sí y
con el código actual.

## 2. Contexto que no debes re-derivar (verificado 2026-09-04/05)

- **Ledger y sus reglas reales** (`plans/README.md`,
  `scripts/validate_plans_ledger.py`): solo se auditan ficheros
  `NNN-*.md` y carpetas `plans/NNN` exactas; los directorios con sufijo
  (`061-...`) son invisibles para el validador; `DONE` en raíz sin
  `KEEP:` es violación; todo token hex entre backticks debe resolver
  como commit git. El ledger debe quedar en OK (`python
  scripts/validate_plans_ledger.py`).
- **Planes 061–079**: DONE y archivados en `plans/archive/` (historial
  preservado con `git mv`). Cubren: publish UX, reload watchdog,
  headlines fail-open, etapas enteras, legibilidad, review loop,
  uncertainty, diversidad del export, stages en excepciones, hooks
  stakes, identity guard, poisoned-export, dry-run removal, backfills
  (diffs), critic+auditor en Quality, preservación de id, leases en
  `start()`, fixes P2 de Codex. **No reabrirlos.**
- **Hallazgos con estado conocido**:
  - `plans/048/`: pendiente legítimo pero bloqueado en humanos (44/200
    registros etiquetados; el corpus etiquetado NO se encontró dentro
    del repo — solo `scripts/label_enrichment_corpus.py` y guías).
    Producción usa `pattern_v1` (`config.toml:165`); el candidato sigue
    aislado por decisión. Único slice de código: accent folding
    (marcado opcional en el propio plan).
  - `plans/060/`: mega-plan de 12 fases (0–11). Hecho en código: 0, 1,
    2a–2c, 3a–3c, 4a, 4c (casi: 2 checks menores). Huecos reales: **4b**
    (0/20, no existe `SourceCatalogWorkflow`), **6** (sin cliente TS
    generado; `apps/admin/src/lib/{api,types}.ts` a mano), **10**
    (correcciones: solo spike `docs/spikes/reader-correction-loop.md**).
    Fases 5/7/8/9/11 sin directorio: 5 parece mayormente implementada
    (webhook + handler + tests de contrato) pese a no tener dir; 11 la
    está haciendo otro agente vía 081 (ver abajo). El `todo.md` maestro
    de 060 está obsoleto como tracker; la fila del ledger es más fiable
    pero ilegiblemente larga.
  - **Trabajo ajeno en vuelo (NO tocar sin coordinar)**: `plans/080/`
    (TODO, handoff de otro agente) y `plans/081/` (IN_PROGRESS) más
    ediciones sin commitear en `AGENTS.md` y `docs/*`. El 080 propone
    "cuatro admin response aliases generados" (solapa con `types.ts`
    manual de 066) y "stateful workflow tests" (solapa con tests de
    078 ya implementados). Cualquier implementación tuya en esas áreas
    duplicaría trabajo: coordina con su dueño primero.
  - Incidentes recientes que cambian el estado real respecto a lo
    escrito: run 18 publicó el artículo equivocado (export con ids
    efímeras; PR #143 cerrado; guard de identidad + export regenerado
    50/50 verificado); run 20 murió por reinicio con lease de 1h
    (recuperación en `start()` añadida); Codex P2s en PR #144
    corregidos a nivel raíz (alt ES + spillover scan).

## 3. Alcance

**Dentro:** leer specs/todos/ledger + verificar cada afirmación contra
el código (`grep`, tests, `git log` de merges reales) para 048 y 060
(fases 4b, 5, 6, 7, 8, 9, 10, 11); actualizar specs, todos y filas del
ledger para que reflejen la realidad; archivar a `plans/archive/` lo
que califique como DONE según las reglas del validador; anotar
solapes con 080/081 sin implementar sobre ellos.

**Fuera:** cambios de código de producto, migraciones, datos de
producción, despliegues, publicación de artículos, commits al repo
frontend, re-entrenar o re-etiquetar corpus, fijar umbrales sin datos.

## 4. Método exigido

1. Por cada plan pendiente: lee spec + todo + fila del ledger.
2. Verifica cada checkbox no trivial contra el código (símbolo existe,
   test lo cubre, merge commit existe). Marca como drift —con
   evidencia citada (fichero:línea, commit)— todo lo que el código
   contradiga. No te fíes de los checks.
3. Para cada hueco real: estima tamaño (S/M/L) y escribe el criterio
   de aceptación que lo cerraría, sin implementarlo.
4. Actualiza fila del ledger por fila tocada (estados válidos:
   TODO/IN_PROGRESS/PARTIAL/DONE/BLOCKED/REJECTED; DONE en raíz exige
   `KEEP:` o archivado).
5. Todo lo que necesite decisión del operador (p. ej. adoptar 048,
   scoping de 4b, reparto con el dueño de 080) va a una sección
   `## Decisiones para el operador` en cada spec, nunca lo asumas.

## 5. Restricciones duras

- `scripts/validate_plans_ledger.py` debe pasar antes y después.
- `make lint` debe pasar si tocas `*.py` (no deberías necesitarlo).
- No commitees trabajo ajeno (080/081 y docs en vuelo son de otro
  agente); no borres nada sin que el ledger lo respalde.
- Commits pequeños con mensajes según estilo del repo
  (`docs(plans): ...`); push a `main` y vigila el CI del push.
- Si encuentras un bug real de producto por el camino, no lo
  arregles: documéntalo como hallazgo con severidad y reproducción.

## 6. Criterios de aceptación

- [ ] Cada plan en `plans/{048,060,080,081}/` tiene estado verificado
      contra código con evidencia citada.
- [ ] Ledger en OK y filas coherentes con los todos.
- [ ] Planes DONE archivados (o con `KEEP:` justificado).
- [ ] Sección de decisiones para el operador completa y sin supuestos.
- [ ] Push en verde (CI + Code Quality).
