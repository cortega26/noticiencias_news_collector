# Plan 060 / Phase 2a: Characterize and harden the v2 fail-closed gate; retire the v1 smoke fixture

**Status:** ready to dispatch. Independent of Phase 2b (no shared files, no ordering
dependency). Does not touch the 30 incomplete posts and does not change
`STRICT_EDITORIAL` behavior anywhere.

**Relationship to the master plan:** this implements master items 1–3 from
[`plans/060/spec.md`](../spec.md) "Phase 2: Restore truthful schema-v2
publication". Items 4–5 are [`phase-2b-corpus-cutover`](../phase-2b-corpus-cutover/spec.md),
which is operator-gated and cannot be dispatched yet.

## Baseline correction — read this before doing anything else

The master plan's evidence baseline (commit `d63cbea`) describes items 1–2 as
outstanding gaps. **They are not.** Commit `65e934a` ("fix(editorial): fail
closed on V2 enrichment missing sources", 2026-08-07) — which predates the
`d63cbea` baseline (2026-08-14) — already added:

- `_V2_REQUIRED_ENRICHMENT_FIELDS` (`news_collector/components/editorial/ai_editor.py:218-227`):
  the six required fields (`summary_points`, `glossary`, `fact_check`,
  `why_it_matters`, `confidence`, `sources`).
- A fail-closed check inside `process_article`
  (`ai_editor.py:2177-2190`): when `schema_version >= 2`, any missing
  required field raises `GeneratedArticleValidationError(error_code="editorial_v2_incomplete")`.
  `GeneratedArticleValidationError` (`ai_editor.py:228-235`) subclasses
  `ValueError` and always carries an `error_code`.
- `RefineryEngine.process_single_article` (`news_collector/logic/workflows/refinery_engine.py:424-450`)
  already catches `ValueError`, reads `error_code`, and on a truthy
  `error_code` returns `False` **before** branch creation (`branch_created`,
  line 530) and before `self.writer.write_article(...)` (line 537). The
  failure is recorded via `record_stage("editor_refinement", False,
  error_code=..., error=...)` and persisted via `persist_attempt(False)`.
- A cache-poisoning guard (`ai_editor.py:1966-1990`,
  `_enrichment_cache_is_usable`): a Stage 4 cache artifact missing any
  required field is treated as poisoned and regenerated rather than
  reused, so a stale incomplete cache can't silently satisfy the gate.
- `_generate_enrichment_fields` (`ai_editor.py:1355-1429`) already falls
  back to `_empty_enrichment_fields()` (all-empty dict) on LLM/validation
  failure, and empty values are correctly caught by the missing-field
  check above — provider failure is not a bypass.

Existing unit coverage: `tests/unit/editorial/test_enrichment_fields.py`
(`test_v2_enforcement_rejects_missing_enrichment_fields`,
`test_v2_enrichment_all_fields_succeeds`, `TestPoisonedStage4Cache::test_poisoned_cache_is_regenerated`,
plus generation/fallback cases in `TestEnrichmentGeneration`).

**What is actually still missing**, and the only things this phase does:

1. **No integration-level test proves the orchestration boundary.** Every
   existing test exercises `process_article` or `_generate_enrichment_fields`
   directly. Nothing in `tests/unit/logic/workflows/test_refinery_engine.py`
   asserts that when `process_article` raises
   `editorial_v2_incomplete`, `RefineryEngine.process_single_article`
   returns `False` **and** `self.git.create_branch` / `self.writer.write_article`
   are never called. This is exactly the "before writer/Git side effects"
   claim in master item 2 — it holds today, but nothing pins it against
   regression.
2. **The v1 smoke fixture still doesn't exercise the real assembly path**
   (master item 3). `frontend_publication_validation.py` hand-builds
   `schema_version: 1` YAML text via `render_fixture_markdown()`
   (`news_collector/logic/workflows/frontend_publication_validation.py:26-78`) —
   it never calls `EditorAgent.process_article`, never touches
   `EnrichmentSchema`, and never exercises the fail-closed gate described
   above. A regression in the gate, in `_generate_enrichment_fields`, or in
   the YAML assembly at `ai_editor.py:2107-2208` would not be caught by
   this fixture.

## Scope

**Backend only** (`noticiencias_news_collector`). No frontend changes in
this phase — `check-editorial-fields.js`, `content.config.ts`, and
`STRICT_EDITORIAL` are all out of scope here (they belong to Phase 2b item 5,
which cannot run until the corpus is clean).

**Files to touch:**
- `tests/unit/logic/workflows/test_refinery_engine.py` — new integration
  test(s) for the fail-closed boundary.
- `news_collector/logic/workflows/frontend_publication_validation.py` —
  replace `build_fixture_post()` / `render_fixture_markdown()` with a
  production-path v2 fixture builder.
- `tests/unit/logic/workflows/test_frontend_publication_validation.py`
  (create if it doesn't already exist — check first) — prove that removing
  each of the six required fields from the new fixture-generation path
  produces a `GeneratedArticleValidationError` with
  `error_code="editorial_v2_incomplete"`, and that the complete fixture
  passes.
- Any snapshot/golden file that pins the old `schema_version: 1` fixture
  text (search for `FIXTURE_ARTICLE_ID` / `_smoke-test` usages before
  starting — check `apps/refinery/` and any CI script that consumes the
  rendered fixture path, e.g. `run_frontend_publication_validation`'s
  callers).

**Files explicitly out of scope (do not touch):** `plans/060/spec.md`,
`plans/060/todo.md`, `plans/060/phase-2b-corpus-cutover/`, any file under
`src/content/posts/` (frontend), `content.config.ts`,
`check-editorial-fields.js`, `check-contract-sync.js`.

## Work

### Step 1 — integration test: fail-closed boundary in `RefineryEngine`

Add to `tests/unit/logic/workflows/test_refinery_engine.py`, following the
existing test class's mocking conventions (it already mocks `self.git`,
`self.db`, `self.editor`/`self.writer` collaborators — read the existing
`setUp`/fixtures before writing new tests, do not reinvent the mock
scaffolding).

Required cases:
1. `self.editor.process_article` (or the real `EditorAgent.process_article`
   if the existing tests use the real class with a stubbed LLM provider —
   match whatever the file already does) raises
   `GeneratedArticleValidationError("...", error_code="editorial_v2_incomplete")`.
   Assert: `process_single_article` returns `False`;
   `self.git.create_branch.assert_not_called()`;
   `self.writer.write_article` (or the mock/spy equivalent) is not called;
   `self._last_blocked_error["error_code"] == "editorial_v2_incomplete"`.
2. A control case: `process_article` succeeds (returns valid v2 markdown) —
   assert the pipeline proceeds past `editor_refinement` to
   `branch_created` (does not need to run the full pipeline to PR creation;
   stop the assertion at whatever point the existing successful-path tests
   in this file already stop).

Do not modify `refinery_engine.py` or `ai_editor.py` — the behavior under
test already exists (see Baseline correction above); this step only adds
coverage.

### Step 2 — replace the v1 smoke fixture with production-path v2 assembly

Before editing, grep the full repo for `FIXTURE_ARTICLE_ID`,
`build_fixture_post`, `render_fixture_markdown`, and `_smoke-test` to find
every caller and every place that asserts on the fixture's exact shape
(there is at least one caller in `frontend_publication_validation.py`
itself around the `run_frontend_publication_validation` orchestration —
read that whole function, not just the builder, before changing the
builder's return type or the file staging logic that depends on it).

Replace `build_fixture_post()` + `render_fixture_markdown()` with a builder
that produces the fixture through the same code path a real article takes:

- Construct a minimal but realistic `raw_text` dict (title, summary,
  content, source_url, source_name — same shape `process_article` expects
  per `ai_editor.py:1680-1745`) long enough to clear
  `self.min_content_length` (check the configured value before picking a
  length; don't guess).
- Call `EditorAgent.process_article(...)` (construct an `EditorAgent` the
  same way other backend tests/fixtures already do — check
  `tests/unit/editorial/test_enrichment_fields.py`'s `setUp` for the
  pattern of stubbing the LLM provider so this fixture generation is
  deterministic and doesn't make real API calls) to produce the full
  markdown (frontmatter + body) exactly as production does, including
  `schema_version: 2` and all six enrichment fields.
- The provider stub must return deterministic, schema-valid
  `EnrichmentSchema`-shaped JSON for every one of the six fields — do not
  invent article content beyond what's needed to make the fixture pass;
  keep it clearly synthetic (title/body should still read as an obvious
  smoke-test article, matching the spirit of the current fixture's own
  disclaimer text).
- Preserve the fixture's existing operational contract: same
  `FIXTURE_ARTICLE_ID` / `FIXTURE_POST_FILENAME` constants (unless a caller
  requires otherwise — check first), same "stage, validate, restore
  workspace" lifecycle in `run_frontend_publication_validation`.

**This is a real behavior change to what gets staged into the frontend
repo, not just a backend refactor.** The old fixture emitted a fixed,
hand-picked set of `AstroPost` keys with no enrichment fields. The new one
will carry every field `process_article` actually produces:
`summary_points`, `glossary`, `fact_check`, `why_it_matters`,
`confidence`, `sources` (each `sources` entry includes a `publisher` key
that can be `None` — see `ai_editor.py:1415-1421`), `refinery_id`,
`headlines_variants`, `requires_uncertainty_note`. This staged file is
what `run_frontend_publication_validation` actually runs `npm run
validate:content` / `build` / `test:dist` / `test:audit` against in the
**frontend checkout** — a `null` `publisher` or an unexpected key reaching
those gates for the first time is exactly the class of bug
`validate_post_frontmatter_fast` exists to catch. Do not treat "the
backend pytest suite is green" as sufficient proof this step works — see
Acceptance below for the required end-to-end run.

Rename `build_fixture_post`/`render_fixture_markdown` only if keeping the
old names would misdescribe what they now do (e.g. they no longer build a
`Pydantic` `AstroPost` by hand) — if you rename, update every caller found
in the grep above in the same commit.

### Step 3 — prove the fixture fails closed on each missing field

New test module (or extend an existing one if `frontend_publication_validation.py`
already has a test file — check first): for each of the six required
enrichment fields, build a variant of the fixture with that field stripped
(via the provider stub returning it empty, not by hand-editing the
rendered markdown — the point is to exercise the real gate, not the YAML
serializer) and assert:

- `EditorAgent.process_article` raises `GeneratedArticleValidationError`
  with `error_code="editorial_v2_incomplete"` naming the missing field.
- The complete fixture (all six fields populated) succeeds and produces
  markdown containing `schema_version: 2` plus all six fields.

**`sources` is a special case — read `_generate_enrichment_fields`
(`ai_editor.py:1355-1429`) before writing it.** When the LLM/stub returns
an empty `sources` list but the raw input carries `source_url` or
`source_name`, the method deterministically backfills a synthetic sources
entry (`ai_editor.py:1409-1421`) — the missing-field gate never fires. A
stub that omits `sources` while the fixture's raw input still has
`source_url`/`source_name` set will produce a **passing** fixture, not a
failing one, contradicting this step's own assertion. For the `sources`
case specifically: build that one variant's raw input with `source_url`
and `source_name` both absent/empty (in addition to the stub returning
empty `sources`), so the backfill cannot fire and the missing-field gate
is what actually rejects it. Assert this explicitly in the test's
docstring/comment so a future reader doesn't "fix" it by re-adding
`source_url`.

This satisfies master Phase 2's acceptance clause "both CI pipelines fail a
partial fixture and pass a complete one" for the **backend producer side**
only — the frontend consumer side of that same acceptance clause is
already covered by the existing `tests/content-config-schema.test.ts`
"STRICT_EDITORIAL enforcement" suite (frontend repo, untouched by this
phase) and remains gated behind `STRICT_EDITORIAL`, which Phase 2b turns on
unconditionally once the corpus is clean. Do not attempt to flip
`STRICT_EDITORIAL` in this phase.

## STOP conditions

- If `render_fixture_markdown`'s output shape (field order, quoting style,
  presence/absence of optional fields) is asserted on byte-for-byte by any
  test or script outside this phase's declared files — stop and report
  which file, rather than loosening that assertion silently.
- If `EditorAgent` cannot be constructed deterministically without a real
  network-calling LLM provider (i.e. no existing stub/fake provider pattern
  exists anywhere in the test suite) — stop and report; do not add a live
  API call to a CI-path fixture.
- If making `frontend_publication_validation.py` call `process_article`
  measurably slows down the smoke test in a way that breaks an existing
  timeout assumption (check for `timeout=` in the calling script/workflow)
  — stop and report the measured delta rather than silently raising the
  timeout.
- If the end-to-end run against a real frontend checkout fails any of
  `validate:content`/`build`/`test:dist`/`test:audit` on the new
  production-path fixture — stop and report which gate and why, rather
  than adjusting the fixture's enrichment content until it happens to
  pass. A failure here means either the fixture builder or a real frontend
  gate has a bug; both are worth surfacing, not papering over.

## Acceptance

- `pytest tests/unit/logic/workflows/test_refinery_engine.py -v` green,
  including the two new cases from Step 1.
- `pytest tests/unit/editorial/ -v` still fully green (no regressions from
  Step 1/2/3 — these steps should not need to touch `ai_editor.py` at all;
  if a change there turns out to be necessary, STOP and report why before
  making it).
- New fixture-generation test module green, covering all six missing-field
  cases plus the complete case.
- `make test` (or the project's standard fast suite) passes.
- **End-to-end fixture run against a real frontend checkout**: run
  `run_frontend_publication_validation` (or whatever entry point/script
  invokes it — check `apps/refinery/` and any CLI wrapper) pointed at an
  actual frontend working copy, with the new production-path fixture, and
  record the exit code. This must actually execute
  `npm run validate:content` / `build` / `test:dist` / `test:audit` against
  the staged `_smoke-test.md` — a mocked or skipped frontend run does not
  satisfy this criterion. Confirm the post-run workspace-restore step
  leaves the frontend checkout clean (`git status` shows no residual
  fixture file or manifest changes) whether the run passes or fails.
- `git diff --stat` touches only the files listed in Scope above.

## Rollback

Revert this phase's commit(s) — it adds tests and replaces a fixture
builder; nothing here changes production behavior (`ai_editor.py`,
`refinery_engine.py`, `target_repo_writer.py` are all read-only in this
phase), so rollback carries no operational risk.

## Done criteria (for `plans/060/todo.md` Phase 2 checklist)

This phase closes:
- [ ] Characterize complete/empty/partial/invalid/cached/provider-failure
      v2 assembly — closes with a caveat: the assembly-level behavior was
      already characterized by pre-existing tests; this phase adds the
      missing **orchestration-boundary** characterization (Step 1) and
      **fixture-level** characterization (Step 3).
- [ ] Fail incomplete new v2 output before writer/Git side effects with a
      stable retryable error code — closes as **already true in
      production code since commit `65e934a`**; this phase adds regression
      coverage, it does not add the behavior.
- [ ] Replace the backend v1 smoke fixture with deterministic
      production-path v2 — closes fully (Step 2).

Do not check these boxes in `plans/060/todo.md` until Phase 2a is merged
and independently verified. Phase 2's remaining three checklist lines
(inventory/human-review, zero strict errors, frontend unconditional
enforcement) stay unchecked — they belong to Phase 2b.
