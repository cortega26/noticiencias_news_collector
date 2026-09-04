# Plan 073 — Stop committing the CI-built export (poisoned ids)

## Finding (plan 072 audit)

`daily_collector.yml` collects into an ephemeral CI DB and commits
`data/exports/latest_articles.json` whose autoincrement ids do not match
production. Every id-keyed consumer is then cross-wired (this caused run
18's wrong-article publish). Consumer audit:

- Refinery cloud path (`temp/source` clone): reads the committed file,
  falls back to the local sibling when absent/mismatching. Safe without
  fresh commits (last good regen stays as baseline; plan-071 guard
  neutralizes stale/wrong ids anyway).
- Frontend repo, `publication-smoke.yml`, `sync-master.yml` (branch
  pointer sync, content-agnostic): no dependency on this file.
- Dev scripts (`debug_json`, `validate_export`, `patch_json_scores`):
  read the local working-copy file; unaffected.
- The job's collection run + failure alert stay intact (health coverage
  preserved); only the commit of the id-bearing artifact goes away.

## Design

Minimal, reversible one-hunk change in
`.github/workflows/daily_collector.yml`: remove the "Commit and Push
Data" step's `git add/commit/push` of the export (keep the job, its
schedule, concurrency and failure alert), with a comment pointing at
plan 071 explaining why CI-built exports must never be committed
(ephemeral ids poison publish-by-id).

Non-goals: changing what the job collects, touching `sync-master`,
backfilling anything, regenerating the export (done in 071).

## Verification

- `python -c yaml.safe_load` parses the edited workflow.
- `git diff` review of the single hunk.
- Push + watch CI (the workflow file itself isn't executed by tests;
  the `docs`/`ci` gates validate workflow syntax on push).
