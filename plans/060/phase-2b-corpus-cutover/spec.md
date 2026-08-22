# Plan 060 / Phase 2b: Review the 30 incomplete v2 posts and cut over to unconditional enforcement

**Status: DECIDED, partially executable.** The operator (2026-08-22) chose
the strategy below. Drafting/inventory work (Work item 1) can be dispatched
mechanically. Per-post review and commit (Work item 2) still requires a
human to check `fact_check`/`sources` against the real source before
anything is marked reviewed — **no subagent may mark a post reviewed or
commit v2 content on the operator's behalf.** Items 3–5 (zero-errors gate,
unconditional enforcement, cross-check) are mechanical once item 2 is done
and can be dispatched then.

**Depends on:** [`phase-2a-v2-failclosed`](../phase-2a-v2-failclosed/spec.md)
merged before any drafted content is committed (the fail-closed gate and
its test coverage should be in place before new v2 content moves through
the pipeline again). Drafting (item 1) does not depend on 2a and may run
in parallel with it — it only reads existing posts and calls
`_generate_enrichment_fields`, it does not touch the writer/Git path.

**Relationship to the master plan:** this implements master items 4–5 of
[`plans/060/spec.md`](../spec.md) "Phase 2: Restore truthful schema-v2
publication".

## Current state (verified 2026-08-22)

- 31 posts carry `schema_version: 2`; 30 fail strict validation; 180
  missing-field errors total. Raw per-error diagnostic dump:
  `noticiencias/tests/fixtures/publication-contract-corpus/v2-strict-failure-inventory.json`
  (Phase 0 deliverable — a flat `{file, message}` error list, **not** yet a
  per-post record with proposed values or evidence links; master item 4's
  "machine-readable inventory... link proposed values to verified
  source/editorial evidence" is genuinely unbuilt work).
- `STRICT_EDITORIAL` gates two independent checkers and is never set to
  `true` anywhere in `.github/workflows/` (frontend repo) — confirmed by
  repo-wide grep. This is the "CI/deploy bypass" master item 5 removes:
  - `noticiencias/src/content.config.ts:104-106` — the Zod `superRefine`
    block that enforces the six v2 fields, currently gated on
    `process.env.STRICT_EDITORIAL === 'true'`.
  - `noticiencias/scripts/check-editorial-fields.js:177` — same gate,
    controls whether `hasErrors` exits 1 (strict) or 0 (informational).
  - `noticiencias/tests/content-config-schema.test.ts` — already has
    passing coverage for both the strict-on and strict-off behavior; when
    the gate becomes unconditional this test's "does not enforce... when
    STRICT_EDITORIAL is not set" case (line 99) must be removed or
    rewritten to reflect that there is no longer an off state.

## Operator decision (made 2026-08-22)

The master plan's own STOP condition applied here: *"no verified evidence
for a historical post... requires an explicit version/fallback decision."*
Three options were on the table — draft-then-approve, fully human-authored,
downgrade to v1 — laid out with a recommendation, and the operator
confirmed the recommendation:

**Draft-then-approve as the default, falling back to downgrade-to-v1
per-post wherever the original source isn't reliably verifiable. Full
human-authoring only as a rare exception** (a draft that turns out to
contradict or badly misrepresent the source, rather than just needing
edits).

Rationale kept for the record: Stage 4 (`_generate_enrichment_fields`) is
the same machinery already producing these fields for every new v2 post,
so drafting first costs little and gives the reviewer something concrete
to react to rather than a blank page. It doesn't cut corners on rigor —
the review cost for `fact_check`/`sources` is the same whether the
starting point is an AI draft or nothing. Posts whose source is dead,
paywalled now, or otherwise unverifiable are not worth forcing into v2;
they downgrade to `schema_version: 1` instead, which the master plan
explicitly sanctions as a legitimate per-post outcome.

**Implementation note:** do not call `EditorAgent.process_article` for
drafting — it re-runs the entire translate/adapt/critic pipeline and would
regenerate `title`, `excerpt`, and `headlines_variants` for an
already-published post, not just enrichment. Call
`_generate_enrichment_fields` directly (it only needs `article_content`,
`article_title`, `source_url`, `source_name` — see
`ai_editor.py:1355-1429`) against each post's existing published body and
frontmatter, so only the six missing fields are drafted and everything
else about the post is untouched.

## Work

1. **Build the per-post inventory with drafts — mechanical, dispatchable
   now, independent of Phase 2a.** For each of the 30 failing posts: read
   the existing frontmatter, call `_generate_enrichment_fields` directly
   (per the implementation note above) using the post's own body/title/
   `source_url`/`source_name` as input, and record the draft output
   alongside a link/reference to the original source (`source_url`) and a
   `reviewed: false` flag. Turn
   `v2-strict-failure-inventory.json`'s flat error list into this
   structured per-post record (JSON, one file per post or one combined
   file — executor's choice, but keep it diffable and reviewable in a PR).
   This step produces drafts only — it must not modify any file under
   `src/content/posts/`, must not commit content changes, and must not
   mark any post `reviewed: true`. If `_generate_enrichment_fields`
   returns empty/fails for a post (e.g. no usable `source_url`), record
   that plainly in the inventory as "no draft available — needs downgrade
   or manual authoring" rather than silently omitting the post.
2. **Review and commit, post by post or in reviewed batches — human gate,
   not dispatchable.** The operator reviews each draft against the real
   source, chooses per post: accept draft (edit as needed), replace with
   human-authored content, or downgrade to `schema_version: 1`. Every post
   that gets v2 fields added must have had a human look at the specific
   `fact_check` and `sources` values against the real source before commit
   — this is the one non-negotiable part regardless of which per-post
   outcome is chosen. Requires Phase 2a merged first (see Depends on).
3. **Zero-strict-errors gate — mechanical, after item 2 is done.**
   `STRICT_EDITORIAL=true node scripts/check-editorial-fields.js --json`
   reports `"errors": []` for the full corpus (31 posts, or fewer if some
   were downgraded to v1 — downgraded posts simply drop out of the v2
   count).
4. **Flip enforcement unconditional — mechanical, dispatchable once item 3
   is green** (only after step 3 is green):
   - `content.config.ts:104-106` — remove the `strictEditorial &&` guard;
     the `schema_version >= 2` branch always runs.
   - `check-editorial-fields.js:177` and its `strictMode` branches — same;
     collapse to always-strict, `process.exit(1)` on any v2 error
     unconditionally.
   - `tests/content-config-schema.test.ts` — remove or rewrite the
     "not enforced when STRICT_EDITORIAL is not set" case (line 99);
     every remaining STRICT_EDITORIAL reference in the test file should
     go with it since the env var no longer changes behavior.
   - Grep for any other `STRICT_EDITORIAL` reference (CONTRIBUTING.md,
     CI docs, dashboard) and correct/remove — re-run the grep from this
     spec's "Current state" section to confirm none remain.
5. **Cross-repo release smoke — mechanical, dispatchable with item 4**
   (master acceptance: "both CI pipelines
   fail a partial fixture and pass a complete one"): confirm Phase 2a's
   backend fixture test (six missing-field cases) and this phase's now-
   unconditional frontend Zod/checker enforcement agree — a partial v2
   fixture fails both sides, a complete one passes both. This is largely
   already proven independently by each side's own tests; this step is a
   final cross-check, not new test infrastructure.

## STOP conditions

- No verified source evidence for a given historical post → that post goes
  to `schema_version: 1` (downgrade), not invented content. This is the
  master plan's own STOP condition, restated.
- Item 1 (drafting) is the only sub-step of this phase safe to dispatch to
  an executor subagent unsupervised. If an executor drafting the inventory
  finds itself about to edit a file under `src/content/posts/`, mark a
  post `reviewed: true`, or otherwise act past "produce a draft for human
  review" — stop and report; that is scope creep into item 2, which stays
  a human gate regardless of how confident the draft looks.
- Material disagreement about what a required field means for a given post
  (e.g. what counts as an adequate `fact_check` entry for an opinion piece)
  → pause that post, do not guess.
- If the operator wants Stage 4 (this phase) to remain non-blocking
  indefinitely rather than reaching zero errors → that is a valid product
  decision, but it means "make v2 semantic enforcement unconditional"
  (item 5) does not happen, and this phase's plan/todo should be updated to
  say so explicitly rather than left silently incomplete.

## Acceptance

- `STRICT_EDITORIAL=true node scripts/check-editorial-fields.js --json`
  reports zero errors on the full corpus.
- `content.config.ts` and `check-editorial-fields.js` enforce v2 semantics
  unconditionally (no `STRICT_EDITORIAL` branch left in either).
- Every post that carries `schema_version: 2` has a review record showing
  a human reviewed its `fact_check`/`sources` values against the original
  source.
- A partial v2 fixture fails both backend (Phase 2a) and frontend
  (this phase) checks; a complete one passes both.

## Rollback

Revert the enforcement-unconditional commit and the content commits
together if the producer side (Phase 2a's gate) cannot yet guarantee
complete v2 output — per the master plan's explicit rule: "never leave CI
permissive while producers claim v2." Do not revert enforcement alone and
leave downgraded/reviewed content in an inconsistent state.
