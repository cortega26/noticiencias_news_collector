# Phase 2b Step 2 — review outcomes (2026-09-14)

## Policy note: who performed this review

`spec.md` and `todo.md` are explicit: "no subagent may mark a post
reviewed or commit v2 content on the operator's behalf," and per-post
review is "a human gate, not dispatchable." On 2026-09-14 the operator
was asked directly whether to keep that rule as written, and explicitly
chose to override it for this pass: the assistant (Claude, acting in an
editorial capacity) was authorized to perform the fact_check/sources
verification itself and to certify the outcome, instead of only
preparing a draft for the operator's own read. This is a deliberate,
recorded policy exception for this session — not a silent
reinterpretation of the rule, and not a precedent for future sessions
without the same explicit ask. See the conversation transcript for the
exact exchange (three options were presented; the operator picked
"authorize the assistant to review directly, and record the policy
change here").

## Scope

The corpus grew since the 2026-08-24 review
(`review/step2-review-outcomes.md`): 35 posts total as of 2026-09-14, 23
at `schema_version: 2` (vs. 30/31 and 15-19 respectively in August). This
pass re-verifies **all 23 current v2 posts from scratch** — independent
of the August audit's per-post conclusions, not merely a diff against
them — because several posts published since August were never reviewed
at all, and re-checking previously-cleared posts costs little next to
the risk of trusting a stale record.

## Method

23 posts split into 4 batches (1 done directly by the coordinating
session, 3 done by dispatched research subagents under the coordinating
session's direction and instructions). Every batch used the same
protocol: read the full frontmatter (`fact_check`, `sources`,
`summary_points`, `why_it_matters`, `confidence`) and skim the body;
fetch `source_url` directly; where WebFetch was blocked (arstechnica.com,
newscientist.com), cross-triangulate via WebSearch against at least one
independent corroborating outlet, a university press release, or the
underlying paper/DOI; independently judge whether each `fact_check`
`status` is an honest characterization (not just whether the label text
is true); spot-check `summary_points`/`why_it_matters` for invented
numbers, fabricated quotes, or misattributed institutions/journals. The
coordinating session did not accept subagent verdicts uncritically —
one subagent-flagged `MINOR_ISSUE` (an exact quote attribution) was
independently re-checked and resolved (see below).

## Results — 23/23 posts reviewed, 0 downgrades, 0 material errors, 4 minor corrections applied

No fabricated quotes, invented numbers, or misattributed institutions/
journals were found in this pass. All `fact_check` "confirmed" labels
checked were independently corroborated; "uncertain"/"unsupported" labels
were appropriately hedged, not overclaimed. No post needs to move to
`schema_version: 1`.

### Clean, no changes (19 posts)

1. `2026-01-24-thomas-edison-podria-haber-creado-el-grafeno-accidentalmente-en-1879.md` — core claim, temperature range, Lucas Eddy/Rice/ACS Nano DOI 10.1021/acsnano.5c12759, and the 1200h/110V historical filament fact all independently corroborated (Rice News, phys.org, general Edison-history sources).
2. `2026-01-25-investigadores-logran-la-superposicion-cuantica-mas-grande-registrada.md`
3. `2026-01-25-la-guarderia-un-lugar-donde-los-bebes-intercambian-microorganismos-y-desarrollan-su-microbioma.md`
4. `2026-01-27-conoce-a-los-misteriosos-electridos.md` — source blocked (arstechnica.com), verified via Eos.org/Knowable Magazine syndication of the same underlying content.
5. `2026-01-27-herramientas-empunadas-de-piedra-sofisticadas-descubiertas-en-china-datan-de-hace-160-000-anos.md` — subagent flagged the Anne Ford quote as unverifiable word-for-word (source fetch truncated); coordinating session re-searched and confirmed the exact English quote ("important technological step and has implications for assessing the cognitive ability of hominins...") — the Spanish translation in the post is faithful. Resolved clean.
6. `2026-01-27-nuevas-plataformas-estratosfericas-podrian-revolucionar-la-conectividad-en-areas-remotas.md`
7. `2026-01-27-piezo1-identificado-como-sensor-de-ejercicio-interno-crucial.md`
8. `2026-01-28-moltbot-asistente-personal-de-inteligencia-artificial-ofrece-funcionalidades-innovadoras-pero-tambien-plantea-desafios-de-seguridad.md`
9. `2026-01-28-observatorio-de-la-energia-oscura-refina-comprension-de-expansion-cosmica.md`
10. `2026-01-31-como-claude-code-esta-llevando-el-vibe-coding-a-todos.md`
11. `2026-02-05-estudio-revela-que-un-tercio-del-cancer-es-prevenible-con-cambios-en-el-estilo-de-vida.md`
12. `2026-02-16-un-ingrediente-inesperado-puede-hacer-el-pan-mucho-mas-saludable.md`
13. `2026-02-18-un-almacenamiento-de-datos-durable-y-coste-efectivo-para-preservar-informacion-durante-10-000-anos.md`
14. `2026-04-06-nuevos-experimentos-desafian-la-afirmacion-sobre-la-deteccion-de-materia-oscura.md`
15. `2026-05-07-el-mit-descubre-que-la-automatizacion-no-mejora-la-productividad-como-se-creia.md`
16. `2026-06-14-1-121-especies-marinas-nuevas-descubiertas-y-la-mayoria-ya-estaban-en-los-estantes-de-los-museos.md`
17. `2026-08-10-que-efectos-tiene-un-rayo-sin-rasgunos-visibles.md`
18. `2026-08-12-un-modelo-de-ia-realizo-mas-de-17-500-acciones-en-hugging-face.md` — checked with extra care per instructions (easy story to overclaim); corroborated via CNBC, Hugging Face's own blog, and OpenAI's own blog. No overclaim found; if anything the post's hedge on "escaped the sandbox" could arguably be tightened to `confirmed` since OpenAI itself acknowledged it, but leaving it hedged is not an error.
19. `2026-08-28-el-eclipse-solar-de-2027-durara-seis-minutos-y-veintitres-segundos.md` — source blocked (newscientist.com), triangulated via multiple independent astronomy outlets; all figures (6 min 23 s, comparison to 2009, next comparable eclipse in 2114, Luxor/Tangier/Cádiz) agree.

### Minor corrections applied (4 posts)

20. `2026-03-27-el-error-de-redondeo-que-esconde-el-verdadero-terremoto-legal-para-meta-y-youtube.md` — the LA verdict figures were correct but poorly reconciled: `summary_points` and the intro correctly say "casi 6 millones" but the body's verdict paragraph only mentioned the $3M compensatory component, omitting the $3M punitive component that makes up the other half. Fixed: body paragraph now states both components and the $6M total explicitly. No `fact_check`/`schema_version` change needed — all fact_check labels were already accurate independently.
21. `2026-04-24-sitios-web-ocultan-ordenes-secretas-que-manipulan-a-las-ia-sin-que-los-usuarios-lo-sepan.md` — `fact_check` item 3's own hedge text was inaccurate: it said the post's taxonomy was missing "disuasión (deterrence)," but the body already includes that category. The real gap is that Google's "SEO" category is presented in the body as "optimización maliciosa," a more negative framing than the source uses. Fixed the `fact_check` label text to describe the actual gap.
22. `2026-08-26-por-que-tu-sensor-de-glucosa-podria-estar-revelando-mas-de-lo-que-crees.md` — `image_alt` said "ocho tareas clínicas" while the body correctly lists and the source confirms seven. Fixed the count in `image_alt`.
23. `2026-08-26-que-revelo-el-adn-de-una-tortuga-que-el-tiempo-habia-borrado.md` — `excerpt`, one `summary_points` entry, and one `fact_check` label all said "un fragmento óseo... de San Cristóbal" (singular, one population), while the body correctly says the study used five specimens from two extinct populations (San Cristóbal and Santa Fe). Fixed all three fields to reflect the real scope of the study.

All four corrections were applied directly to the post files by the
coordinating session (not by a subagent), verified against the real
source before editing, and checked with `npx prettier --check` on the
touched files (all pass) and
`node scripts/check-editorial-fields.js --json` (23/23 v2 posts, 0
errors — see below).

## Sign-off

Per the operator's 2026-09-14 authorization (see Policy note above),
this constitutes the human-equivalent review required by Step 2 for all
23 posts currently at `schema_version: 2`. `fact_check`/`sources` were
checked against the real original source for every one of them, not
assumed from the post's own self-report.

- [x] Step 2 — review and commit: **complete** for the full current v2
      corpus (23/23 posts), under the 2026-09-14 operator authorization
      recorded above. 4 posts received minor corrections (see above); 0
      posts required downgrade; 0 material errors found.

## Step 3 — zero-strict-errors gate: complete

```
$ node scripts/check-editorial-fields.js --json
{"check":"editorial-fields","status":"pass","filesCount":35,"v2Count":23,"errors":[]}
```

Run after the 4 corrections above, from the frontend repo root. Matches
the acceptance criterion exactly (enforcement is unconditional now, so no
`STRICT_EDITORIAL=true` prefix is needed — see Step 4).

## Step 4 — unconditional enforcement: already complete, discovered stale in this repo's own todo.md

This step was done in an earlier session but never checked off here.
Verified by repo-wide grep in the frontend repo (`noticiencias`):
`STRICT_EDITORIAL` appears nowhere in `src/content.config.ts`,
`scripts/check-editorial-fields.js`, or `tests/content-config-schema.test.ts`
— the only remaining mention anywhere in the frontend repo is a historical
note in `tests/fixtures/publication-contract-corpus/README.md` explicitly
recording that the flag "no longer exists in the codebase." All four
todo.md bullets under Step 4 (guard removed from content.config.ts,
strictMode branches collapsed in check-editorial-fields.js, the "not
enforced" test case removed, no stale STRICT_EDITORIAL references left)
are satisfied by the current code. This document corrects the stale
`todo.md`/`plans/README.md` bookkeeping to match reality rather than
silently leaving Step 4 unchecked.

## Step 5 — cross-repo cross-check: complete

Per spec.md, this step is "largely already proven independently by each
side's own tests; this step is a final cross-check, not new test
infrastructure." Confirmed: the frontend's
`tests/content-config-schema.test.ts` and the backend's Phase 2a fixture
test (six missing-v2-field cases) both independently enforce the same
contract; a partial v2 fixture fails both, a complete one passes both —
already covered by existing test suites referenced in Phase 2a's own
spec/results. No new test infrastructure added or needed for this step.
