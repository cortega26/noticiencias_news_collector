# Plan 060 / Phase 2b todo: Review the 30 incomplete v2 posts and cut over to unconditional enforcement

Execution index for [`spec.md`](spec.md). **Step 0 is resolved** (operator
decision made 2026-08-22: draft-then-approve default, downgrade-to-v1
fallback). **Step 1 is dispatchable now**, independent of Phase 2a. **Step 2
is a human gate — never dispatch it to an executor subagent.** Steps 3–5
are dispatchable once Step 2 is complete and Phase 2a is merged.

## Step 0 — operator decision (RESOLVED)

- [x] Operator chose: draft-then-approve as default, downgrade to v1 where
      source isn't verifiable, human-authored only as a rare exception —
      see spec.md "Operator decision (made 2026-08-22)".

## Step 1 — inventory with drafts (DONE, merged to main)

- [x] Per-post inventory built from `v2-strict-failure-inventory.json`:
      one record per post with current frontmatter, missing fields, source
      link (`source_url`), draft field values from `_generate_enrichment_fields`
      (called directly per spec.md's implementation note — not via
      `process_article`), and `reviewed: false`. Live corpus cross-checked
      against the stale fixture: zero discrepancy. Real NVIDIA provider
      confirmed used (`nvidia/nemotron-3-super-120b-a12b`, 30/30 attempt
      log lines, 0 Ollama fallback). 27/30 posts drafted on the first pass;
      3 flagged with shallow Pydantic validation errors (not bad sources)
      were retried on 2026-08-23 with the same method and no code changes
      — all 3 succeeded. **30/30 posts now have drafts.**
- [x] Posts where `_generate_enrichment_fields` returns empty/fails marked
      plainly as "no draft available — needs downgrade or manual
      authoring", not silently omitted.
- [x] No file under `src/content/posts/` modified; no post marked
      `reviewed: true`; nothing committed to the frontend repo. Frontend
      checkout verified clean before and after.

See `inventory/README.md` and `inventory/v2-corpus-draft-inventory.json`
for the full output, including caveats: `source_name`/`publisher` values
are synthesized from URL domains (not real corpus data — verify against
the real source), and `fact_check` status is model-asserted against the
already-published body only, not against the original source.

## Step 2 — review and commit (human gate — not dispatchable)

- [ ] Every post reaching `schema_version: 2` has had a human check
      `fact_check`/`sources` against the real source.
- [ ] Posts without verifiable evidence downgraded to `schema_version: 1`
      explicitly, not left ambiguous.
- [ ] Phase 2a merged before any drafted content is committed.

## Step 3 — zero-strict-errors gate

- [ ] `STRICT_EDITORIAL=true node scripts/check-editorial-fields.js --json`
      reports `"errors": []` for the full corpus.

## Step 4 — unconditional enforcement

- [ ] `content.config.ts:104-106` — `strictEditorial &&` guard removed.
- [ ] `check-editorial-fields.js:177` — `strictMode` branches collapsed to
      always-strict.
- [ ] `tests/content-config-schema.test.ts` — "not enforced" case (line 99)
      removed/rewritten.
- [ ] Repo-wide `STRICT_EDITORIAL` grep re-run; no stale references left
      (docs, CI, dashboard).

## Step 5 — cross-repo cross-check

- [ ] A partial v2 fixture fails both Phase 2a's backend test and this
      phase's frontend enforcement.
- [ ] A complete v2 fixture passes both.

## Close out

- [ ] `plans/060/todo.md` Phase 2 remaining checklist lines (inventory,
      zero strict errors, frontend unconditional enforcement) checked off.
- [ ] This file fully checked off.
