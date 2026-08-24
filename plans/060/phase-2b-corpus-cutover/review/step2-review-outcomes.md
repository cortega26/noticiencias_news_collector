# Phase 2b Step 2 — review outcomes (2026-08-24)

## What happened

The operator commissioned an independent adversarial audit (a different AI
assistant, real web access, following the prompt this session wrote for
Phase 2b Step 1) against all 30 drafted posts, checking each `fact_check`
claim and `sources` entry against the real `source_url`. The full report
is saved at
[`../inventory/adversarial-audit/noticiencias-v2-adversarial-audit.md`](../inventory/adversarial-audit/noticiencias-v2-adversarial-audit.md).

**This audit is evidence for the operator's review, not the review
itself.** Per spec.md: "no subagent may mark a post reviewed or commit v2
content on the operator's behalf," and every post reaching
`schema_version: 2` needs a human check of `fact_check`/`sources` against
the real source before commit. The operator directed and supplied this
audit; final per-post sign-off (`reviewed: true`) is still theirs to give,
not something this session set unilaterally. **No post in this corpus has
`reviewed: true` as of this document.**

## A finding beyond the audit's own scope: body-level errors, not just metadata gaps

The audit's `CONTRADICTED`/`UNSUPPORTED` findings were checked against the
30 posts' already-*drafted* v2 metadata. Before acting on any of them,
Claude independently checked every `CONTRADICTED`/`UNSUPPORTED` finding
against the corresponding **published article body** in
`noticiencias/src/content/posts/` — not assumed, read directly.

Result: in several posts, the same false or unsupported claim the audit
flagged in the draft **is already live in the published body text**, not
just in the pending v2 metadata. The most serious case:
`2026-01-18-nasa-se-prepara-...-artemis-ii.md`'s body attributes a quote to
NASA Administrator Isaacman claiming Artemis II "enviará estadounidenses a
Marte." The real NASA source (fetched directly, 2026-08-24) contains no
such quote — the real Isaacman quote says nothing about Mars. This is a
fabricated quote attributed to a real named official, live on a published
page, independent of anything to do with the v2 enrichment gate.

This changes what "accept with edits" can safely mean for an affected
post: editing the *metadata* to say a claim is unsupported while the
*body* two screens below still asserts it as fact would leave the post
self-contradictory — worse than today's state — and it would still pass
the strict gate once enforcement goes unconditional (Phase 2b Steps 3-4).

## Operator decision (2026-08-24)

Presented with the count below, the operator chose: **posts with a
confirmed or borderline body-level error downgrade to `schema_version: 1`
alongside the 6 posts the audit already flagged for unreachable sources.
Body-text correction is queued as a separate editorial pass, not done in
this session.** This keeps Phase 2b's original scope (add/verify the six
v2 metadata fields) intact for the remaining posts, whose bodies check out
clean.

## Final classification (30 posts)

### Downgraded to `schema_version: 1` — 15 posts, DONE (commit pending)

**Original 6 (audit: source unreachable, unrelated to body content):**
1. `2026-01-27-conoce-a-los-misteriosos-electridos.md` — source HTTP 403
2. `2026-01-27-desafio-global-contra-el-sarampion-por-falta-de-confianza-en-las-vacunas.md` — source access restricted
3. `2026-01-27-nuevas-plataformas-estratosfericas-podrian-revolucionar-la-conectividad-en-areas-remotas.md` — source access restricted
4. `2026-02-12-bienvenidos.md` — source URL is a category page, not an article
5. `2026-03-27-el-error-de-redondeo-que-esconde-el-verdadero-terremoto-legal-para-meta-y-youtube.md` — source access restricted
6. `2026-06-12-los-chatbots-rescataron-a-elias-thorne-de-una-conversacion-casual-y-lo-convirtieron-en-una-ficcion-masiva.md` — source paywalled

**New, this session — confirmed body-level factual errors (Claude verified each against the real body text and, for one, against the real source directly):**
7. `2026-01-15-cursos-en-linea-abren-puertas-a-nuevas-carreras.md` — body asserts the subject currently works as an SCM professional; source says he's a current master's student.
8. `2026-01-17-cientificos-descubren-adn-preservado-en-guepardos-momificados.md` — body claims DNA was extracted from all seven mummified cheetahs; source doesn't support that.
9. `2026-01-18-nasa-se-prepara-para-un-paso-historico-en-la-exploracion-espacial-humana-con-artemis-ii.md` — **severe**: body contains a fabricated quote attributed to NASA Administrator Isaacman about sending Americans to Mars; verified directly against the real NASA source, which contains no such statement.
10. `2026-01-23-descubren-los-arpones-mas-antiguos-una-revelacion-que-cambia-nuestra-perspectiva-sobre-la-caza-de-ballenas.md` — body misattributes the discovery to "científicos brasileños" and misidentifies the whale species as blue whales; source says neither.
11. `2026-02-16-un-agujero-negro-se-forma-sin-explotar-una-estrella-masiva.md` — body repeats a physics error (convection "delaying" core collapse) the source contradicts.
12. `2026-05-15-un-asteroide-de-700-metros-rota-cada-1-88-minutos-desafiando-teorias-astronomicas.md` — body states as fact that Rubin has already observed a failed supernova; source describes only a candidate and future capability.

**New, this session — borderline (unsourced or partially-hedged claim present in the body, downgraded per the operator's conservative default):**
13. `2026-01-31-estudio-revela-menor-agrupamiento-de-galaxias-de-lo-esperado.md` — body's limitations paragraph (selection bias, image-distortion uncertainty) isn't supported by the audited source.
14. `2026-04-02-comunicacion-laser-como-desbloqueara-datos-gigantes-y-video-hd-para-las-misiones-lunares-tripuladas.md` — body poses (as a rhetorical question) real-time family videoconferencing the source doesn't support.
15. `2026-05-23-un-cohete-con-un-motor-apagado-y-otro-fallando-llego-al-espacio-y-volvio.md` — body's Artemis III/Starship-2028 framing is more confident than the source's own hedged timeline.

All 15: `schema_version: 2` → `1` in frontmatter, applied and verified
(`node scripts/check-editorial-fields.js --json` shows exactly 16 v2 posts
remaining, `npm run lint` clean). Not yet committed — see Next steps.

### Remaining v2, metadata-only edits needed — 15 posts (NOT YET APPLIED)

Audit confirmed these posts' bodies are clean — the only corrections
needed are in the drafted v2 metadata fields (`sources[].title/publisher/
date`, individual `fact_check` labels/statuses, trimming unsupported
`why_it_matters`/`summary_points` overreach), per the audit's specific
per-post findings:

1. `2026-01-24-thomas-edison-podria-haber-creado-el-grafeno-accidentalmente-en-1879.md`
2. `2026-01-25-investigadores-logran-la-superposicion-cuantica-mas-grande-registrada.md`
3. `2026-01-25-la-guarderia-un-lugar-donde-los-bebes-intercambian-microorganismos-y-desarrollan-su-microbioma.md`
4. `2026-01-27-herramientas-empunadas-de-piedra-sofisticadas-descubiertas-en-china-datan-de-hace-160-000-anos.md`
5. `2026-01-27-piezo1-identificado-como-sensor-de-ejercicio-interno-crucial.md`
6. `2026-01-28-moltbot-asistente-personal-de-inteligencia-artificial-ofrece-funcionalidades-innovadoras-pero-tambien-plantea-desafios-de-seguridad.md`
7. `2026-01-28-observatorio-de-la-energia-oscura-refina-comprension-de-expansion-cosmica.md`
8. `2026-01-31-como-claude-code-esta-llevando-el-vibe-coding-a-todos.md`
9. `2026-02-05-estudio-revela-que-un-tercio-del-cancer-es-prevenible-con-cambios-en-el-estilo-de-vida.md`
10. `2026-02-16-un-ingrediente-inesperado-puede-hacer-el-pan-mucho-mas-saludable.md`
11. `2026-02-18-un-almacenamiento-de-datos-durable-y-coste-efectivo-para-preservar-informacion-durante-10-000-anos.md`
12. `2026-04-06-nuevos-experimentos-desafian-la-afirmacion-sobre-la-deteccion-de-materia-oscura.md`
13. `2026-04-24-sitios-web-ocultan-ordenes-secretas-que-manipulan-a-las-ia-sin-que-los-usuarios-lo-sepan.md`
14. `2026-05-07-el-mit-descubre-que-la-automatizacion-no-mejora-la-productividad-como-se-creia.md`
15. `2026-06-14-1-121-especies-marinas-nuevas-descubiertas-y-la-mayoria-ya-estaban-en-los-estantes-de-los-museos.md`

## Status (2026-08-24, updated)

1. **Done, merged**: the 15 downgrades, `noticiencias` PR
   [#133](https://github.com/cortega26/noticiencias/pull/133). Included a
   follow-up fix in the same PR (per an automated review comment) removing
   the fabricated Isaacman/Mars quote directly from the Artemis II post's
   body — downgrading `schema_version` alone doesn't stop a post from
   rendering, so the fabricated quote would otherwise have stayed live.
   The other 8 downgraded posts' body issues (overclaims, not fabricated
   quotes) remain queued for a separate editorial pass.
2. **Done, PR open**: the audit's specific per-field corrections applied to
   the inventory JSON's `draft` object and the actual post frontmatter for
   all 15 remaining v2 posts — `noticiencias` PR
   [#134](https://github.com/cortega26/noticiencias/pull/134). Per-post
   corrections (source titles/publishers/dates, `fact_check` labels/
   statuses, trimmed `why_it_matters`/`summary_points`) are listed in that
   PR's description and traceable to specific audit findings above.
   `check:editorial-fields`: 16/16 v2 posts pass, 0 errors.
3. **`reviewed: false` on all 30 posts, deliberately.** Applying the
   audit's corrections is not the same as the operator doing the final
   read-through the spec requires before a post claims verified v2 status.
   This session did not set `reviewed: true` anywhere — that flag is the
   operator's to set, once they've done their own pass (informed by, but
   not identical to, the audit this document is built on).
4. **Not done**: correcting the 8 remaining downgraded posts' body-level
   overclaims (queued, separate editorial pass, per the operator's
   decision — see the downgrade list above).

## Original next-steps note (superseded by Status above, kept for history)

1. Commit the 15 downgrades as a discrete unit (this document + frontmatter changes).
2. Apply the audit's specific per-field corrections to the inventory JSON's
   `draft` object and the actual post frontmatter for the 15 remaining
   posts, per post, using the audit's findings verbatim.
3. Leave `reviewed: false` on all 30 posts in the inventory JSON until the
   operator does a final pass and explicitly says which posts to mark
   `reviewed: true` — this session applying audit-derived corrections does
   not, by itself, satisfy the spec's human-review gate.
4. The 9 newly-downgraded posts' body-level errors are **not fixed** —
   queued as a separate editorial correction pass, per the operator's
   decision. They remain live on the site with the errors documented
   above until that pass happens.
