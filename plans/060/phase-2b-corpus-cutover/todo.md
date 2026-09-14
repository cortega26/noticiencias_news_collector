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

## Step 2 — review and commit (human gate — not dispatchable, except by explicit operator override)

- [x] Every post reaching `schema_version: 2` has had a human (or, per the
      2026-09-14 operator authorization below, human-equivalent) check of
      `fact_check`/`sources` against the real source. Prior state (two
      independent AI audit rounds — round 1:
      `inventory/adversarial-audit/noticiencias-v2-adversarial-audit.md`;
      round 2: `noticiencias/docs/audits/phase2b-second-independent-audit.md`,
      `noticiencias` PRs #133/#134/#136/#137/#138) was evidence for the
      operator's review, not a substitute, per spec.md's "no subagent may
      mark a post reviewed... on the operator's behalf." **On 2026-09-14
      the operator was asked directly and explicitly authorized the
      assistant to perform this review itself instead** (a recorded,
      one-time policy override, not a silent reinterpretation — see
      `review/step2-review-outcomes-2026-09-14.md` "Policy note" for the
      exact exchange). Under that authorization, all 23 posts currently at
      `schema_version: 2` (the corpus grew from 30/31 to 35 total since
      August) were independently re-verified from scratch against their
      real sources — not a diff against the old audit. Result: 19/23
      clean, 4/23 got minor corrections (metadata/body reconciliation, not
      factual retractions), 0 downgrades, 0 material errors. Full record:
      `review/step2-review-outcomes-2026-09-14.md`.
- [x] Posts without verifiable evidence downgraded to `schema_version: 1`
      explicitly, not left ambiguous. 15 posts downgraded (6 unreachable
      source, 9 confirmed/borderline body-level errors found during this
      session's independent verification) — `noticiencias` PR #133,
      merged. 15 remaining posts got their v2 metadata corrected per the
      audit's findings — `noticiencias` PR #134, merged. Round 2: 3 of the
      6 originally-unreachable-source posts had their source come back and
      were promoted to v2 after independent re-verification — `noticiencias`
      PR #137, merged. `check:editorial-fields`: 19/19 v2 posts pass, 0
      errors, even under `STRICT_EDITORIAL=true`.
- [x] Phase 2a merged before any drafted content is committed — confirmed,
      merged earlier in Plan 060.

## Step 3 — zero-strict-errors gate

- [x] `node scripts/check-editorial-fields.js --json` reports
      `"errors": []` for the full corpus (`filesCount:35, v2Count:23,
      errors:[]`, 2026-09-14, after the 4 Step 2 corrections). No
      `STRICT_EDITORIAL=true` prefix needed — see Step 4.

## Step 4 — unconditional enforcement

- [x] `content.config.ts` — `strictEditorial &&` guard already removed
      (found already done during the 2026-09-14 pass; not reflected here
      until now — this repo's own todo.md was stale, see
      `review/step2-review-outcomes-2026-09-14.md` Step 4 for the
      verification grep).
- [x] `check-editorial-fields.js` — `strictMode` branches already
      collapsed to always-strict (same verification).
- [x] `tests/content-config-schema.test.ts` — "not enforced" case already
      removed (same verification).
- [x] Repo-wide `STRICT_EDITORIAL` grep re-run 2026-09-14: zero references
      in frontend source/tests; the only remaining mention anywhere is a
      historical note in
      `tests/fixtures/publication-contract-corpus/README.md` explicitly
      recording the flag's removal.

## Step 5 — cross-repo cross-check

- [x] A partial v2 fixture fails both Phase 2a's backend test and this
      phase's frontend enforcement; a complete one passes both — already
      covered by existing suites on both sides (frontend
      `tests/content-config-schema.test.ts`, backend Phase 2a's fixture
      test), reconfirmed 2026-09-14. No new test infrastructure needed,
      per spec.md's own framing of this step.

## Close out

- [x] `plans/060/todo.md` Phase 2 remaining checklist lines (inventory,
      zero strict errors, frontend unconditional enforcement) checked off.
- [x] This file fully checked off.
