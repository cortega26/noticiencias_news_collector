# Plan 082 — Hallazgos sobre planes pendientes (para ahorrar trabajo)

> **Qué es esto:** notas de campo de una revisión 2026-09-04/05. Sin
> autoridad sobre tu trabajo: tómalo como evidencia verificada para ir
> más rápido, decide tú el resto.

## 1. Plan 048 (enrichment registry): pendiente de humanos, no de código

- Bloqueado en etiquetado: 44/200 registros revisados; la decisión
  formal adopt/no-adopt espera a ≥200 (`plans/048/todo.md`, 4 checks
  abiertos).
- El corpus etiquetado NO se encontró dentro del repo (solo
  `scripts/label_enrichment_corpus.py` + guías) — si lo necesitas,
  pregunta al operador dónde vive.
- Producción usa `pattern_v1` (`config.toml:165`); el candidato sigue
  aislado tal como se decidió. Nada roto.
- Único slice de código a la vista, marcado opcional en el propio plan:
  matcher accent folding.

## 2. Plan 060 (12 fases 0–11): estado real verificado contra código

- Hecho: 0, 1, 2a–2c, 3a–3c, 4a, 4c (de 4c quedan 2 checks menores: la
  validación "live con PR real" ya ocurrió con los runs 18/21, falta
  solo nota de docs).
- Huecos con ausencia real de código: **4b** (0/20, no existe
  `SourceCatalogWorkflow`), **6** (sin cliente TS generado;
  `apps/admin/src/lib/{api,types}.ts` a mano), **10** (correcciones:
  solo `docs/spikes/reader-correction-loop.md`).
- Fases 5/7/8/9/11 sin directorio: la 5 parece mayormente implementada
  (webhook + handler + tests de contrato) aunque no tenga dir; la 11
  la estás trabajando tú vía 081.
- Ojo: el `todo.md` maestro de 060 está obsoleto como tracker (fases
  hechas figuran abiertas); la fila del ledger es más fiable pero
  ilegiblemente larga.

## 3. Mecánica del ledger (verificada leyendo el script)

- `scripts/validate_plans_ledger.py` solo audita ficheros `NNN-*.md` y
  carpetas `plans/NNN` exactas; los directorios con sufijo
  (`061-...`) son invisibles para él.
- `DONE` en raíz sin `KEEP:` es violación; todo token hex entre
  backticks debe resolver como commit.
- Mis planes 061–079 están archivados en `plans/archive/` con historial
  (`git mv`); cubren publish UX, reload watchdog, headlines fail-open,
  etapas enteras, legibilidad, review loop, uncertainty, diversidad del
  export, stages en excepciones, hooks stakes, identity guard,
  poisoned-export, dry-run removal, backfills (diffs), critic+auditor,
  preservación de id, leases en `start()`, fixes P2 de Codex.

## 4. Incidentes recientes que cambian lo escrito (por si los ves raros)

- Run 18 publicó el artículo equivocado (export de CI con ids efímeras
  vs DB de producción); PR #143 cerrado; guard de identidad +
  export regenerado 50/50 verificado (plan 071).
- Run 20 murió por reinicio con lease de 1h y bloqueaba publishes con
  409; recuperación en `start()` añadida (plan 078, con matiz
  NULL-heartbeat documentado en su spec).
- Codex P2s en PR #144 corregidos a raíz (alt ES + spillover scan,
  plan 079). Los diffs de las 2 instancias están en el historial del
  chat, no en repo.

## 5. Solapes que detecté con tu 080/081 (informativo, no directivo)

- "Cuatro admin response aliases generados" ↔ mi `types.ts` manual
  (plan 066).
- "Stateful workflow tests" ↔ tests de leases de 078 (ya implementados
  y en verde).
- Si te sirven como punto de partida o prefieres otro enfoque, a tu
  criterio.
