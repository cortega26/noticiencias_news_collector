# Plan 064 — Etapas del editor con números enteros (1–7)

## Goal

Los logs del pipeline muestran `STAGE 2.5`, `STAGE 2.6`, `4.5`… Renumerar a
enteros secuenciales en orden de ejecución:

| Antes | Después | Etapa |
|---|---|---|
| 1 | 1 | Scientific Translation |
| 2 | 2 | Editorial Adaptation |
| 2.5 | 3 | Critic Pass (Validation & Repair) |
| 2.6 | 4 | Editorial Critic Gate (Quality) |
| 3 | 5 | Metadata & Headlines (+ headline critic gate) |
| 4 | 6 | Editorial Enrichment Fields |
| 4.5 | 7 | Fact-Check Verification |

## Scope

Solo etiquetas humanas: `print("--- STAGE ...")`, docstrings y comentarios
en `ai_editor.py`, comentarios en `frontend_publication_validation.py`,
descripciones en `noticiencias/config_schema.py` + `docs/config_fields.md`,
y comentarios/cadenas citadas en tests. **NO** se tocan identificadores de
almacenamiento (`stage2_5_critic_ok`, `stage4_enrichment`, … en
`_get_cache_path` — renombrarlos huérfana cachés en disco), ni las etapas
1–9 de `docs/PRODUCT_FLOW.md` (son del pipeline global, otro concepto), ni
la nota histórica `docs/refinery_stage3_push_collision_fix.md`.

Orden de reemplazo (los literales `Stage 3/4` son subcadenas de `3.5/4.5`):
primero `4.5 → 7`, `3.5/2.5/2.6 → 5/3/4`, y al final `STAGE/Stage 3 → 5`,
`STAGE/Stage 4 → 6`.

## Verification

- `grep` post-cambio: cero `Stage [12].[56]`, `Stage 3.5/4.5` en `*.py`
  (fuera de histórico/PRODUCT_FLOW).
- `make lint` + suites tocadas: `test_ai_editor_coverage`,
  `test_refinery_engine`, fact-check/enrichment/publication-validation tests.
