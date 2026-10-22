# Plan 190 validation record — 2026-10-21

Risk: CRITICAL. Implementation checkout: `fix/editorial-image-wait-20261021`,
base `f23e2d211bd5dd8d8d2af63463af2a823800f0e5`. Shared source WIP was
preserved. Unpublished implementation commits were consolidated before push
after renaming a public storage identifier falsely flagged by Gitleaks; the
secret detector and its exceptions were unchanged.

## Automated gates

- `make lint`: passed (Black, isort, Ruff and repository lint helpers).
- `make type`: passed; 4389 passed, 5 opt-in/CI-only skips; unit coverage
  89.99%, baseline 88.44%, changed-file ratchet passed. This is the repository's
  incremental mypy plus full unit coverage gate, not a new strict-mypy claim.
- `make test`: 4380 passed, 5 skipped before the nine additional coverage
  regressions; final `make type` runs all 4389 tests successfully.
- `make test-integration`: 116 passed / 1 opt-in skip, then 189 root E2E-marked
  cases passed.
- `make test-e2e`: 14 passed, including the real sibling frontend build/audit.
- `make perf`: 9 passed.
- `make test-contracts`, `make test-boundaries`, `make quality-gate`,
  `make quality`: passed. Existing security severity/allowlist and non-blocking
  Semgrep policy were retained; no thresholds or suppressions were weakened.
- `make admin-test`: 96 passed. `make admin-lint`, `make admin-build`,
  `make admin-contracts-check`: passed.
- `make docs-check`, `make inventory-check`, `make plans-ledger-check`: passed.
- Fresh independent lifecycle review: 85 focused cases passed, no material gap;
  E2E raster correction separately reviewed. Final coverage cases: 70 focused
  tests passed. Tests use real SQLite/files and fake external seams only.

The initial E2E run exposed a fixture URL rejected by the current frontend's
JSON-LD image contract. The harness now uploads a decoded owned local raster;
the corrected full E2E suite passed without weakening frontend checks.

## Database-copy acceptance: article 3822

The canary uses the actual source article from a SQLite backup of the shared
backend database. Every canary write points at an isolated copy; the active
service database was not migrated or mutated. Configured remote LLMs and the
independent local factual verifier performed the editorial work. Only the
canary's editing-provider order was overridden after actual provider failures;
no shared routing configuration changed.

Run 88 completed editorial work with no image: `editorial_completed_count=1`,
`waiting_for_image_count=1`, `errors=[]`, no public Markdown written. The parked
row had no heartbeat. A second durable publication slot (run 89) was acquired
while 3822 waited; complete second-article processing is also covered by the
workflow/admin regressions.

The generated image was uploaded through the actual multipart admin route with
prompt, tool, hash and dimensions. Its callback dispatched the original run.
Replay used the saved source snapshot, retained canonical identity and created
frontend [PR #336](https://github.com/cortega26/noticiencias/pull/336), commit
`fa663c7293d5afdcbff24cc0e7283a4d1707c4de`. A guard on `prepare_article` recorded
**zero calls during replay**; a source-export loader guard was never reached.
The final run is `succeeded`, with one PR and no image wait. A fresh repository
lookup returns `(88, True)` for the completed request. `published_at` and
`published_url` remain null: creating a PR did not claim publication.

The canary's config/DB factory and target-checkout provisioning were redirected
for isolation. Editor, sealed draft, storage, upload, reconciler, workflow,
frontend validation, Git push and PR creation used the implementation unchanged.
An earlier harness input lacked the production contract normalization and
correctly invalidated its fingerprint; the acceptance run uses identical
normalization on preparation and replay. An isolated dependency symlink naming
problem was also corrected before the final successful replay.

A second copy exercised the actual Alembic chain from `e3f168a66d38` to
`f190a1b2c3d4`: 86 workflow rows before/after, one pending checkpoint preserved,
`PRAGMA integrity_check=ok`. Downgrade refused with the documented pending-wait
preservation guard. No live downgrade was attempted.

Runtime artifacts remain under the implementation checkout's
`output/canary-3822/`; generated asset/prompt under `output/imagegen/`.
A compact archive (including the sealed checkpoint and generated asset) is also
preserved at `data/runtime/plan190-canary-20261021/` in the shared backend
checkout. It is canary evidence, not an active live request. Generation evidence
is committed in `3822-image-generation.json`; the image
itself is committed in the frontend PR, not duplicated into this backend PR.

## Frontend and browser acceptance

The final candidate passed `npm run lint`, `npm run typecheck`,
`npm run validate:content`, `npm run build`, `npm run test:dist` and
`npm run test:audit` (90 files, 987 tests). No public content-schema changes.
At 375px and 1280px: all images decoded, no horizontal overflow, descriptive
Spanish alt, visible IA caption exactly once, production canonical and OG image
path valid; the built OG resource returned HTTP 200 locally. The cutaway keeps
roots and hyphae readable at both widths. Screenshots and machine results:
`output/playwright/3822-{375,1280}.png` and `3822-browser-summary.json`.

The unmodified localhost preview emitted two Cloudflare RUM CORS transport
errors. The application/image browser check was repeated with that telemetry
endpoint isolated (204 fixture): zero application console errors. This is
explicitly a local-preview limitation, not production telemetry proof.
Admin mocked-network browser acceptance independently verified image waiting
without ETA/stall, second-article processing, reload/back recovery and PR handoff;
`output/playwright/admin-waiting-browser-summary.json` records no console errors.

## Release boundary and remaining owner work

Implementation and canary validation are complete; production rollout remains
pending review/merge approval. Apply the migration before compatible backend
and admin, following `docs/PIPELINE_CONTRACTS.md`. Preserve all checkpoints on
rollback and stop the reconciler before reverting code.

Frontend PR #336 is deliberately a **draft**: the existing editorial policy
admitted the article with a recoverable critic caveat (average 8.4, rigor 5/10),
and two factual checks remain uncertain. It needs editorial approval. Its
publication attempt exists in the canary copy; it is not evidence in the live
service. Do not merge it as production publication until the real backend
request/attempt has been correlated after rollout. No merge, deploy or live
publication has been claimed.

## Dependency review follow-up

Socket identified [GHSA-8g5g-8vmr-9782](https://github.com/advisories/GHSA-8g5g-8vmr-9782)
in the initially promoted Pillow 12.3.0. The patched release is Pillow 13.0.0;
all four locks are regenerated with the repository sync script. Streamlit
1.66.1 supports Pillow 13 and replaces the fallback's incompatible 1.54.0
constraint. The AppTest entrypoint fixtures now use absolute paths, matching
current Streamlit path resolution. The public image-rights wait reason also
has a Spanish label and a regression test.

The isolated SAST lock resolves MCP 1.30.0 to Semgrep 1.180.0's required
1.29.0. This is an explicit tool-only resolver correction under the existing
SAST isolation/security policy, not a runtime dependency or new waiver. Other
resolver deltas are confined to Pillow, Streamlit and its required transitives.
The task uses a private Python environment; the shared environment was preserved.
