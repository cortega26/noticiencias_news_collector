# Plan 076 — Critic + auditor signals in the review loop

## Goal

The Quality page shows readability and stage checklists but not the two
editorial judgments that matter most: the editorial-critic verdict
(avg, approved?) and the auditor state. Both exist today but are
unqueryable (critic avg is log-only; auditor lives in per-article
metadata). Persist/surface them without changing any return contract.

## Design (two slices)

A. Critic verdict stage (no signature changes anywhere):
1. `EditorAgent.__init__`: `self.last_critic_verdict = None`.
2. `_critic_editorial_pass`: stash
   `{"approved", "average", "scores"}` on the approved AND rejected
   terminal branches (early fail-open returns leave it untouched).
3. `refinery_engine.py` after `editor_refinement` success: read via
   `getattr` (mock editors lack it → skipped, zero breakage) and
   `record_stage("editorial_critic", approved, average=...)`. Success
   mirrors the verdict (a published-with-caveat article shows a red
   critic row — honest and exactly the review signal).
4. Tests: unit both verdicts; engine stage present with values.

B. Auditor state on quality rows:
1. `AdminQualityRunItem` += `audit_state: Optional[str]` (additive).
2. Endpoint batch-fetches `article_metadata.audit.state` for numeric
   article_ids in ONE query inside the session; missing → None.
3. `quality.astro`: 7th column badge (passed verdigris / failed rose /
   pending amber / — ink); `types.ts` mirror.
4. Tests: seeded Article audit metadata surfaces; others None.

Non-goals: critic thresholds, auditor rollup stats, changing
`process_article`/`_critic_editorial_pass` signatures, frontend repo.

## Verification

- `make lint && make type && make test && make test-contracts &&
  make test-boundaries`; admin `check + test + build`; live `/quality`
  snapshot.
