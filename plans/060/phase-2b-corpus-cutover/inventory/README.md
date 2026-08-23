# v2 corpus draft inventory — Phase 2b Step 1

Machine-generated **drafts for human review**. Nothing here is published,
committed to the frontend, or marked reviewed. See
[`v2-corpus-draft-inventory.json`](./v2-corpus-draft-inventory.json) for
the full per-post records.

## Counts

- Posts processed: **30** (all `schema_version: 2` posts in the frontend
  corpus that are missing at least one of the six required enrichment
  fields, cross-checked against the live working tree — not just the
  stale inventory fixture).
- Drafts produced (`draft_available: true`, all six fields non-empty):
  **27**.
- No draft available (`draft_available: false`): **3**.
- Of the 27 available drafts, **0** came back with any of the six fields
  still empty (`draft_empty_fields` is empty on every available record).
- Run was **not** halted early (`halted_early: false`); the >10-failure
  stop condition was not triggered (3 failures total).

### The 3 posts with no draft available

- `2026-01-27-conoce-a-los-misteriosos-electridos.md`
- `2026-01-27-desafio-global-contra-el-sarampion-por-falta-de-confianza-en-las-vacunas.md`
- `2026-04-06-nuevos-experimentos-desafian-la-afirmacion-sobre-la-deteccion-de-materia-oscura.md`

**Important:** all 30 posts carry a `source_url` in frontmatter, so none
of these three failed because of a missing source (the condition the
original task description named as one trigger for `draft_available:
false`). All three failed because the NVIDIA response did not pass
`EnrichmentSchema` Pydantic validation (see `failure_reason` on each
record, and `Enrichment Schema Validation Failed` entries in the run log).
This is a schema-validation failure per post, not evidence that the
source itself is unusable — a reviewer or a retry may still be able to
produce a draft for these three. They should **not** be read as
automatic "downgrade to v1" candidates without checking why validation
failed.

## LLM provider / model actually used

Confirmed by construction-time inspection (`EditorAgent.provider`) **and**
by counting attempt log lines across the full run, not assumed:

- `get_provider()` resolved a `FallbackProvider` with chain
  `[NvidiaProvider, OllamaProvider]`, primary = `NvidiaProvider`.
- Model: **`nvidia/nemotron-3-super-120b-a12b`**.
- Log evidence across all 30 posts: **30** `"attempting generate_sync with
  NvidiaProvider"` lines, **0** `"attempting generate_sync with
  OllamaProvider"` lines. The Ollama fallback was never actually invoked —
  every one of the 30 posts (including the 3 failures) was served by the
  real NVIDIA provider from the `.env` credentials. The 3 failures were
  NVIDIA responses that a real call returned but that failed
  `EnrichmentSchema` validation, not provider fallback.

## Method

- Called `EditorAgent._generate_enrichment_fields(article_content=...,
  article_title=..., source_url=..., source_name=...)` directly on a real
  `EditorAgent` instance, constructed the same way
  `apps/refinery/main.py` does (`resolve_ollama_stage_models` +
  `load_config()`). **`EditorAgent.process_article` was never called** —
  no title/excerpt/headlines_variants regeneration happened for any post.
- Prompt template: `config/prompts.yaml` → `enrichment.system`.
- Article body was read from the frontend working tree (read-only) and
  sampled to a maximum of 4000 characters via `_sample_for_critic` before
  being sent to the model, per the existing production behavior of
  `_generate_enrichment_fields`.
- **`source_name` is synthesized, not sourced from data.** No post's
  frontmatter carries a `source_name` field. For every post,
  `source_name` was derived from the domain label of `source_url` (e.g.
  `scientificamerican.com` → `"Scientificamerican"`) and passed into both
  the LLM prompt context and the deterministic sources-backfill inside
  `_generate_enrichment_fields`. **Consequence:** any `sources[].publisher`
  or `sources[].title` value in these drafts may be an agent-derived
  string, not a value that existed anywhere in the corpus. Reviewers
  should verify publisher names against the real source rather than
  trusting them as given.
- **`fact_check[].status` is model-asserted, not verified.** The model
  only ever saw the already-published Spanish article body (truncated to
  4000 chars) — it never saw the original source article. A `"confirmed"`
  status means "consistent with the post's own text," and carries **no**
  verification weight against the real source. Per the phase-2b spec,
  checking `fact_check` and `sources` against the original source is the
  one non-negotiable human-review step before any post is marked
  `reviewed: true`.

## Quality flags found in the drafts

- `2026-04-24-sitios-web-ocultan-ordenes-secretas-que-manipulan-a-las-ia-sin-que-los-usuarios-lo-sepan.md`
  contains a mixed-script artifact — a fragment of Chinese text (理解)
  embedded in otherwise-Spanish prose in one of the draft fields. This is
  a raw LLM output defect, left as-is for the reviewer to see and correct
  (not silently cleaned up). No other post's draft matched the non-Latin
  script scan.

## Live corpus vs. stale inventory file — cross-check result

**Zero discrepancy found.** The stale fixture
(`tests/fixtures/publication-contract-corpus/v2-strict-failure-inventory.json`,
generated at frontend commit `582ed40`) was compared against the live
frontend working tree at HEAD `54ad1501ab990ef239dd0be6b391cd01b781ab9b`:
same 30 files with missing fields, and identical per-file missing-field
sets on both sides. All 30 posts were missing all six required fields
(`summary_points`, `glossary`, `fact_check`, `why_it_matters`,
`confidence`, `sources`) on both the stale fixture and the live corpus.
The stale inventory file was safe to use as the starting point for this
run; no post needed to be added or removed from its list.

## Frontend checkout integrity

`git status` in the real frontend checkout
(`/home/carlos/VS_Code_Projects/products/noticiencias/noticiencias`) was
confirmed clean before this run started and confirmed clean again after
it finished. No file under `src/content/posts/` was modified, created, or
deleted; no git command was run in that checkout.
