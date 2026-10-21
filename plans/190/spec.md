# Plan 190 — Editorial processing independent of images

Risk: CRITICAL (publication lifecycle and SQL status migration).

## Accepted behavior

Finish and durably save editorial preparation without an image. Missing, failed,
placeholder, or unproven-rights images defer only publication. Resume the same
request after an approved asset is staged; no repeated editorial LLM work, duplicate
PR, source-export dependency, or loss on restart. Keep editorial gates closed and
retain existing frontend schema, publication identity and deployed callbacks.

## Interfaces and implementation

- `EditorAgent.prepare_article(raw_text, override_date=None, explicit_article_id=None)`
  returns sealed `EditorialDraft` (content, normalized frontmatter without media,
  source identity, critic verdict, grounding notes). It runs the existing editorial
  gates. `assemble_article(draft, image_url, image_alt, image_origin)` applies media
  and validates AstroPost. `process_article` keeps its existing signature/str result
  as a prepare+assemble wrapper. Draft preview Markdown is internal only.
- Persist typed checkpoints per article in `WorkflowRun.run_metadata`, through a
  storage repository. Include original input, prepared draft, canonical identity,
  fingerprint/version, brief reference and per-item outcome. The fingerprint
  ignores media and includes input, prompts/editor configuration/policy. A resumed
  run loads its original snapshot and checks current editorial configuration;
  changed editorial inputs invalidate the draft, media-only changes do not.
- Engine/pipeline results explicitly distinguish `waiting_for_image` from errors.
  Keep processed_count as PR-success count, add editorial/pending counts. Batches
  continue all items and only resume pending items, preserving failures/successes.
- Add `waiting_for_image` publication-only API status and SQL CHECK migration.
  Atomically save checkpoints before parking. Waiting rows hold no global queued/
  running slot, heartbeat or completed timestamp. CAS resumes the original row;
  the existing global publication single-flight index remains authoritative.
  Retry requests reuse the pending request; ready/finished revisions reuse evidence.
- Reconcile at startup, upload completion, worker completion and every 15s while
  serving. Busy slots leave durable pending rows. Stop/join the reconciler at
  shutdown. Recover queued resume rows after crashes without regenerating drafts.
- Remove dispatch 409 image_required; keep concurrent conflict. Regenerate admin
  OpenAPI/types and display waiting without running ETA/stall warnings.
- Reuse image briefs, validate newly staged origin (unknown cannot release a new
  request), record optional generation prompt/tool/hash/dimensions with backward
  compatible defaults. Codex uses built-in imagegen during the active session;
  generated asset 3822 is scientifically reviewed, staged as ai_generated and
  resumes the original request. No API billing integration or auto-merge.

## Verification

Regression tests: image absent/rights unknown/editorial rejection; durable draft
roundtrip and fingerprint invalidation; restart/export removal; image-ready/busy
race and duplicate upload/click; mixed/all-pending batch; no LLM work on unchanged
resume; SQL migration upgrade/downgrade preserving checkpoints; API/UI waiting;
AI disclosure once and valid final AstroPost. Use real temporary SQLite/files;
mock only network/LLM/GitHub boundaries. Do not run tests on live DB.
The deterministic E2E harness stages a decoded, owned local raster fixture,
so its publication also exercises the frontend's real image/JSON-LD contract.

Required gates: make lint, type, test, test-contracts, test-boundaries, quality-gate,
admin-test, admin-lint, admin-build, admin-contracts-check, docs-check,
inventory-check, plans-ledger-check; focused integrations/migrations. Run frontend
lint/typecheck/validate:content/build/test:dist/test:audit on publication candidate,
verify 375px/1280px console/images/canonical/og:image. Real bounded 3822 canary uses
DB copy before any live request. Distinguish local/CI/PR/deployed evidence.

## Delivery and safety

Isolated worktree at f23e2d21; preserve all shared WIP. Own spec/todo/tests in this
folder; never overwrite root task files. Document migration-before-code rollout
and rollback that preserves drafts and disables auto-resume. Publishing is via PR
only; no merge or destructive DB changes. Mark completed only with evidence;
provider/runtime limitations must remain explicit.
