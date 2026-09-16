# TODO — Social Distribution paquete 1 (contrato + stamping)

Derivado de `spec.md`. Marcar al verificar, no antes.

## Paso 1 — Preparar alcance y preservar workspace
- [x] Capturar SHAs / árbol sucio de ambos repos en `spec.md` §0
- [x] Leer instrucciones vigentes (FE `AGENTS.md`, BE `docs/AGENTS.md` §0.1/§3/§10)
- [x] Crear `plans/social-distribution/{spec.md,todo.md,tests/}` sin tocar 080/081
- [x] Confirmar que `validate_plans_ledger.py` no exige fila para un dir no numérico

## Paso 2 — Tests del contrato y productor (fallan hasta el paso 3)
- [x] `BE tests/unit/contracts/test_social_publication.py` (nuevo) — identidad + preservación + LLM ignorado + vector de hash
- [x] `BE tests/unit/contracts/test_frontend_schema.py` — social: defaults, rechazo `'true'`/`0`/`1`, `id` obligatorio si publish, patrón, clave extra, `null`, `id` con publish:false
- [x] `BE tests/decompose_refinery/test_target_repo_writer.py` — nuevo con/sin fuente, reescritura preserva id/false/ausencia + cuerpo, YAML previo inválido bloquea, fast-validation de la salida
- [x] `FE tests/social/contract.test.ts` (nuevo) — mismos casos equivalentes sobre el schema real

## Paso 3 — Schema + stamping coordinados
- [x] `BE frontend_schema.py` — `SocialConfig` + `AstroPost.social`
- [x] `FE src/content.config.ts` — `social` object + regla cruzada en superRefine + `SOCIAL_ID_RE`
- [x] `BE contracts/social_publication.py` (nuevo) — `derive_social_id`, `apply_social_decision`, `stamp_social_frontmatter`
- [x] `BE target_repo_writer.py` — llamada a `stamp_social_frontmatter` en `write_article`
- [x] `FE .contract-snapshots/frontend_schema.snapshot.json` — `npm run sync:contract-snapshot`

## Verificación (§4 del spec)
- [x] BE: `make lint` — OK
- [x] BE: `make type` (mypy full) — OK, exit 0
- [x] BE: `pytest tests --ignore=tests/e2e_pipeline` — 2285 passed, 5 skipped
- [x] BE: `make test-contracts` — 124 passed, cobertura 89% (gate 80%)
- [x] BE: `make test-boundaries` — 3 passed
- [x] BE: `bandit` sobre los archivos nuevos/modificados — sin hallazgos
- [~] BE: `make quality` — falla por 4 tests PREEXISTENTES en
      `tests/e2e_pipeline/test_pipeline_e2e.py` (`frontend_audit_failure`),
      confirmados fallando idénticamente con mis 3 archivos revertidos a HEAD.
      `make lint`, `make type` (mypy full, exit 0) y `bandit` (archivos nuevos)
      verdes por separado; semgrep/pip-audit no llegaron a correr (sin deps nuevas)
- [x] BE: `make docs-check` — OK (14 docs)
- [x] FE: `npx vitest run tests/social` — 12 passed
- [x] FE: `npm run check:contract-sync` (--strict) — OK, paridad total
- [x] FE: `npm run sync:contract-snapshot` — snapshot regenerado (6 modelos anidados)
- [x] FE: `npm run validate:content` — astro check 0 errores sobre 234 archivos
- [x] FE: `npm run check:doc-drift` — exit 0 (2 avisos preexistentes de plan 081, ajenos)

## Descubierto durante el trabajo
- El editor (`ai_editor.py`) NO valida contra `AstroPost(**llm_dict)` — `model_dict`
  se arma con campos calculados; el `except ValidationError` de esa zona no tiene un
  `AstroPost(...)` vigente. Añadir `social` a `AstroPost` no afecta el gate del editor.
- `check-contract-sync.js` ignora comentarios dentro del cuerpo del `z.object`: un
  campo Zod precedido por `//` no se parsea. `social` va sin comentario inline.
- `test:audit` FE tiene 1 fallo PREEXISTENTE (`check-doc-drift.test.ts`) por refs
  `npm run typecheck` en docs que el plan 081 dejó sin commitear. No es de este paquete.
- Pendiente para paso 11 / operador: documentar el campo `social` en
  `docs/PIPELINE_CONTRACTS.md` (archivo en edición por plan 081 — no tocado aquí).

## Revisión independiente (2026-09-06) — correcciones aplicadas
- [x] `social_publication.stamp_social_frontmatter`: validar el archivo **anterior**
      antes de los early-return del lado generado. Antes, un generado sin fence /
      con YAML inválido devolvía el contenido tal cual **sin** comprobar el previo,
      así que el único caso con ambos lados rotos sobrescribía en silencio una
      decisión editorial guardada. + test unitario y de writer.
- [x] `_is_usable_source_url`: `urlsplit` con esquema http/https **y host no vacío**
      en lugar de un `startswith`. Antes `source_url: "http://"` producía
      `publish: true` con el hash de una cadena sin host. + tests parametrizados.
- [x] `SOCIAL_ID_RE`: `\Z` en vez de `$`. El `re` de Python acepta un `\n` final
      donde Pydantic (rust-regex) y Zod anclan a fin de entrada; el símbolo está en
      `__all__` y lo consumirán los paquetes 2/4. + test de paridad en ambos repos.
- [x] `FE tests/social/contract.test.ts`: caso espejo de id con espacios / `\n`.
- [x] `BE test_target_repo_writer.py`: regeneración sobre un archivo con formato
      prettier (comillas, listas indentadas) — se preserva la decisión previa y
      **todos** los valores generados sobreviven el round-trip.

### Evidencia de fallos preexistentes (método aislado, sin restaurar archivos)
- FE `npm run test:audit` → 1 fallo (`check-doc-drift.test.ts`) por
  `npm run typecheck` en `docs/report-pipeline-setup.md:46` y
  `docs/supported-dependency-matrix.md:50`; `git show HEAD:<archivo>` confirma que
  esas referencias **no existen en HEAD** (las introdujo el plan 081 sin commitear).
  `npm run lint` añade 2 fallos de `prettier --check` en docs del plan 081.
- BE `make type` / `make quality` → 4 fallos en `tests/e2e_pipeline` con
  `failure_class=frontend_audit_failure`, que es exactamente ese
  `npm run test:audit` sobre el workspace FE sucio.
- Comprobado en `git worktree` desechable del FE en `790ce62` (+ solo los archivos
  sociales copiados): `npm run lint` exit 0, `check-doc-drift` OK,
  `check:contract-sync` OK; y con `NOTICIENCIAS_FRONTEND_ROOT` apuntando a ese
  worktree, **`tests/e2e_pipeline` pasa 13/13** con el backend sucio.
  ⇒ Los 5 fallos son del plan 081, no de este paquete.

### Riesgo de merge (no bloquea el paquete 1)
- `scripts/check_doc_review.py` protege `news_collector/contracts/`. `make docs-review`
  pasa hoy **solo** porque el plan 081 tiene sucios `docs/ARCHITECTURE.md`,
  `docs/SOURCE_OF_TRUTH.md`, etc. Un commit únicamente social fallaría esa puerta:
  el paso 11 de §26 (docs BE/FE) debe entrar en el mismo commit o antes.

## Cierre — paquetes 2–7 + rollout vía Buffer (2026-09-14)

Los paquetes 2–7 del plan (§26 pasos 4–10: manifiesto, transporte, copy,
ledger, adaptadores, orquestación, workflow) más el rollout (§26 pasos
12–15) se implementaron y verificaron en el repo frontend. Este `todo.md`
solo cubría el paquete 1, así que se cierra aquí con evidencia en vez de
reconstruir casillas retroactivas.

Verificado en producción 2026-09-14 (todo en `cortega26/noticiencias`):
- [x] FE PR #163 (pkg 7: adaptador Buffer, `publish.js`, workflow) + PR #164
      (fix: `--execute` llegaba a `runDistribution` como `dry-run`; el job de
      publish hacía cero mutations en silencio) — ambos mergeados a `main`,
      CI verde incl. Codacy
- [x] `doctor` verde: 1 org + 3 canales Buffer (facebook/x/linkedin);
      rama `social-state` inicializada (`init-state`, rev 0)
- [x] Primer publish real (run 34897448358): modo `publish`,
      `mutation_count: 3`, `exit_code: 0`, sin warnings — facebook PUBLISHED,
      x PUBLISHED, linkedin ACCEPTED (reconcilia a sent en runs siguientes);
      ledger `social-state` en rev 7; re-runs no duplican
- [x] Kill switch operativo: `SOCIAL_PUBLISH_ENABLED=false` + cancelar el run
      activo; `SOCIAL_PLATFORMS` limita por red

Abierto / diferido (no bloquea el MVP Buffer):
- [ ] Bluesky: sin cuenta todavía — faltan `BLUESKY_DID` / `BLUESKY_PDS_URL` /
      `BLUESKY_APP_PASSWORD` (fase 3 del rollout, §22)
- [ ] `workflow_dispatch` con `mode=reconcile` no llega al CLI (el job usa
      `--execute` fijo); solo importa para reconciliación manual
