# Plan 060 / Phase 4b: Safe source-catalog mutation and batched listing

> Part of Plan 060, master spec.md "Phase 4: Make admin collection and
> source mutation real workflows" (lines 429-457) — this sub-phase covers
> the source-catalog half of that phase's two concrete defects (work items
> 3 and 4). The collection-run half is
> [`phase-4a-collection-run-workflow`](../phase-4a-collection-run-workflow/spec.md).
> Depends on nothing from 4a — these touch disjoint endpoints and files
> and can be built/reviewed independently, though both share the
> single-writer deployment decision recorded below.

## Why this phase exists

`news_collector/config/sources.py`'s `save_sources()` truncates and
rewrites `sources.yaml` directly, with no lock and no atomicity — a crash
mid-write leaves a corrupt or partial catalog file, and two admin requests
racing (however unlikely under today's traffic) can interleave writes.
Separately, `admin_list_sources` issues one DB query per source (N+1) to
fetch circuit-breaker state.

## Recon findings (this session, code-verified via a dedicated Explore pass)

**Current source-catalog mutation, exactly:**
- `news_collector/config/sources.py`'s `save_sources(new_sources)`
  (`sources.py:121-136`) opens `sources.yaml` directly in `"w"` mode and
  `yaml.dump`s the whole catalog — a direct truncating write, **not**
  atomic. No temp file, no `os.replace`, no lock.
- Contrast: `admin_save_prompts` in the same `api.py` file
  (`api.py:1378-1412`) already does `tempfile.mkstemp(dir=...)` +
  `os.replace` for `config/prompts.yaml` — an existing, working atomic-write
  precedent in this exact codebase. This phase applies the same pattern to
  `sources.yaml`, not a new invention.
- `admin_delete_source` (`api.py:1660-1684`) and `admin_upsert_source`
  (`api.py:1686-1732`) each mutate the in-process `ALL_SOURCES` dict, call
  `save_sources(ALL_SOURCES)`, and **separately** call
  `manager.delete_source`/`manager.upsert_source` against SQLite — two
  independent, non-transactional writes with no compensation if the
  second (DB) write fails after the first (YAML) succeeds.
- `validate_sources()` (`sources.py:170-273`) already exists and does
  full-catalog validation, raising `ValueError` with an aggregated message
  — directly reusable, not new work.
- `admin_list_sources` (`api.py:1229-1252`) loops
  `for source_id in sorted(ALL_SOURCES): circuit = manager.get_source_circuit_state(source_id)`
  — one DB round trip per source, confirmed N+1. `SourceRepository`
  (`source_repository.py:21-310`) has no batch equivalent; `DatabaseManager`
  (`database.py:711-726`) just thin-delegates the same one-at-a-time
  surface.

**No file-locking primitive exists anywhere in this codebase** — a
repo-wide grep for `fcntl`, `filelock`, `FileLock`, `flock`, `portalocker`
(excluding `.venv*`/`mutants/`/`temp/source`) found zero real usages; the
one match (`tests/unit/refinery/test_main_coverage.py:120`) tests an
unrelated "is this OS error a file-busy error" classifier, not a lock
acquisition. Work item 3's "documented process/file lock" has to be built
from scratch.

**Deployment topology** (full evidence in
[phase-4a's spec](../phase-4a-collection-run-workflow/spec.md#recon-findings-this-session-code-verified-via-a-dedicated-explore-pass----see-the-investigation-transcript-for-exact-citations),
same finding, repeated here since it's this phase's actual STOP condition):
`Dockerfile.serving` runs plain `uvicorn` with no `--workers`,
`docker-compose.serving.yml` defines one `serving` service with no
replica config, SQLite is the deliberately-chosen production database.
Nothing in the tracked repo declares "single-writer" as a binding
constraint, but nothing contradicts it either — `docs/database_deployment.md`
uses the same "not discoverable in this repository, but no evidence
against it" framing for an identical question raised by plan 046.

## Operator decisions (2026-08-26)

- **Single-writer deployment, documented as a binding assumption.**
  `SourceCatalogWorkflow` uses a real advisory file lock
  (`fcntl.flock`, POSIX — matches the tracked deployment's Linux
  container target; no cross-platform requirement evidenced anywhere in
  this repo) around the YAML read-modify-write section. This closes the
  actual race under the deployment this repo's own tracked config
  describes, without the much larger scope of a Git-backed write path.
  **This assumption must be written down somewhere a future operator
  changing the deployment topology would see it** — see Design §4.

## Design

### 1. `SourceCatalogWorkflow` (`news_collector/logic/workflows/source_catalog_workflow.py`, new)

Follows the same convention as `CollectionRunWorkflow` (Phase 4a) and the
established pattern from `RefineryEngine`/`PROrchestrator`: constructor
`__init__(self, db_manager, *, sources_yaml_path=None, lock_timeout_seconds=...)`,
module logger, public methods return typed results rather than raising for
expected failure modes.

- `mutate(self, mutation_fn: Callable[[dict], dict]) -> SourceCatalogMutationResult` —
  the single entry point every source mutation (`upsert`, `delete`,
  `toggle`, `reset_circuit`) goes through, so the lock/validate/write/sync/
  compensate sequence exists exactly once:
  1. Acquire the file lock (`fcntl.flock(fd, fcntl.LOCK_EX)`) on a
     dedicated lock file (not the YAML file itself — locking the file
     you're about to atomically replace via `os.replace` is fragile,
     since the replaced inode is a different file than the one you
     locked; use `sources.yaml.lock` alongside it, matching common
     practice for this exact pitfall). Bounded wait via
     `lock_timeout_seconds`, not indefinite blocking — return a typed
     "catalog locked, try again" result on timeout rather than hanging
     the request.
  2. Read the current on-disk YAML fresh (not the in-process `ALL_SOURCES`
     cache — another process, or a prior request, may have changed it
     since this process last loaded it).
  3. Apply `mutation_fn` to produce the candidate full catalog.
  4. Run `validate_sources()`-equivalent full-catalog validation against
     the candidate (reuse the existing function; adapt its signature if
     it currently only validates the loaded global state rather than an
     arbitrary dict — check at implementation time). A validation failure
     returns a typed error result immediately, before touching disk.
  5. Write the candidate catalog to a same-directory temp file
     (`tempfile.mkstemp(dir=sources_yaml_path.parent)`, matching
     `admin_save_prompts`'s exact precedent) and `os.replace` it over
     `sources.yaml`.
  6. Synchronize SQLite (`SourceRepository.upsert_source`/`delete_source`/
     `set_source_active` as appropriate to the mutation) inside the same
     locked section.
  7. **If step 6 fails:** restore the prior YAML (the temp-file pattern
     means the pre-mutation content is still recoverable — either keep an
     in-memory copy of the pre-mutation YAML text captured in step 2, or
     copy the about-to-be-replaced file aside before step 5;
     the in-memory copy is simpler and this phase doesn't need to survive
     a *process* crash between steps 5 and 6, only an in-request DB
     failure). If the restore write itself also fails (e.g. disk full),
     do **not** silently swallow this — persist a `reconciliation_required`
     marker (a new small table, or reuse `workflow_runs` with
     `run_type='source_catalog_reconciliation'` if Phase 4a's migration
     has landed first — check at implementation time which is less
     invasive) and return a typed result surfacing this to the caller,
     since the catalog is now in a genuinely inconsistent state a human
     needs to look at.
  8. Release the lock (via context manager / `finally`, not manually, so
     a mid-sequence exception can't leak a held lock).
- `load(self) -> dict` — thin wrapper reading the current on-disk YAML
  fresh, for read-only callers (e.g. the list route) that don't need the
  lock.

### 2. HTTP layer changes (`serving/api.py`)

- `admin_upsert_source`, `admin_delete_source`, `admin_toggle_source`,
  `admin_reset_source_circuit` (`api.py:1660-1732`, `1254-1290`) each call
  `SourceCatalogWorkflow.mutate(...)` with a small closure expressing just
  that endpoint's change to the candidate dict, instead of directly
  touching `ALL_SOURCES`/`save_sources`/`manager.*` as they do today.
  Preserve every existing response-shape/status-code contract the current
  tests assert (see Test impact below) — this is a mechanism change
  underneath, not a behavior change at the HTTP boundary, except for the
  new "reconciliation required" and "catalog locked" error paths, which
  are genuinely new response shapes this phase adds.
- `admin_list_sources` (`api.py:1229-1252`) calls the new batched
  `SourceRepository.get_source_circuit_states(ids)` (Design §3) once,
  composing it with one `SourceCatalogWorkflow.load()` call — "one catalog
  read plus one DB query" per the master plan's acceptance criterion,
  replacing the current per-source loop.
- No new workflow logic added to `serving/` beyond request
  parsing/response mapping — matches master plan work item 5.

### 3. `SourceRepository` batching

Add `get_source_circuit_states(self, source_ids: Iterable[str]) -> dict[str, dict]`
to `SourceRepository` (`source_repository.py`) — one `SELECT ... WHERE id
IN (...)` query returning a `{source_id: circuit_state_dict}` mapping,
same shape as today's per-call `get_source_circuit_state` return value so
`admin_list_sources` can swap the loop for one dict lookup with minimal
surrounding change. Keep the existing single-id
`get_source_circuit_state` method — other callers may still want a single
lookup; this is an addition, not a replacement.

### 4. Document the single-writer assumption

Add a short, findable note — check `docs/database_deployment.md` first
(it already carries the equivalent note for the SQLite-as-production-DB
decision and is the natural home) or `AGENTS.md` if that doc is more
"active" per this repo's own doc-follows-code convention — stating: source
catalog mutations assume a single writer process; the file lock is
advisory and does not protect against a second concurrently-deployed
instance. If deployment ever becomes multi-instance, this workflow needs
revisiting (Git-backed write path, or a real distributed lock) before
re-enabling concurrent catalog edits.

## Test impact

- `test_admin_delete_source_removes_yaml_and_db`
  (`tests/test_serving_admin_api.py:1286-1332`) and
  `test_admin_delete_source_unknown_404` (`:1335-1340`) monkeypatch
  `sources_mod.ALL_SOURCES`/`sources_mod.save_sources` directly — once
  routes call `SourceCatalogWorkflow.mutate(...)` instead, these tests'
  monkeypatch strategy needs updating to patch the workflow (or its
  YAML path) rather than the module globals it used to touch directly.
  The asserted *behavior* (delete removes from both YAML and DB; unknown
  id is 404) must not change.
- `test_admin_upsert_source_creates` (`:1366-1410`) and
  `test_admin_upsert_source_update_preserves_existing_keys` (`:1413-1474`)
  assert default-seeding on create and merge-preserve semantics on
  update (untouched keys like `blacklisted`/`etag` survive; provided keys
  like `name`/`url` overwrite). **This merge-preserve behavior is exactly
  what `mutate`'s candidate-catalog construction must preserve** — the
  `mutation_fn` closure for upsert needs to merge into the existing
  per-source dict, not replace it wholesale.
- `test_admin_upsert_source_validation_422` (`:1477+`) — a missing
  required field returns 422; confirm `SourceCatalogWorkflow.mutate`'s
  validation-failure path still surfaces as 422 at the HTTP layer, not
  some new status code.
- `test_admin_prompts_save_is_atomic` (`:1060+`) is the existing template
  for the equivalent `sources.yaml` atomicity test this phase should add
  (assert a simulated write failure mid-sequence leaves the original file
  intact, not truncated/corrupt).
- New tests needed (none of this exists today, confirmed by recon): lock
  contention (two `mutate` calls racing, one waits/times out rather than
  corrupting the file); DB-sync failure triggers YAML restore; restore
  failure triggers the `reconciliation_required` path; batched
  circuit-state lookup returns identical data to the old per-source loop
  for the same inputs (a regression-equivalence test, not just "it
  returns something").

## Scope boundaries

**In scope:** `SourceCatalogWorkflow`, the four source-mutation routes,
`admin_list_sources`'s batching, `SourceRepository.get_source_circuit_states`,
the single-writer documentation note, and the test rewrites/additions
above.

**Out of scope (Phase 4a or later):** anything under `/v1/admin/collect*`,
`workflow_runs`, `CollectionRunWorkflow` — all Phase 4a. A Git-backed
write path for source mutations (explicitly the road not taken per the
operator's decision above). Multi-instance/distributed locking.

## STOP conditions

- If `validate_sources()`'s actual signature can't cleanly validate an
  arbitrary candidate dict (e.g. it's tightly coupled to reading
  `ALL_SOURCES` as a global rather than accepting a dict argument) without
  a larger refactor than "adapt its signature" — stop and report the
  actual shape before deciding whether to refactor it or write a parallel
  validation path, rather than guessing which is less invasive.
- If step 7's restore-on-DB-failure needs to survive a process crash
  between steps 5 and 6 (not just an in-request exception) — i.e. if
  there's a real operational reason recovery must be crash-safe rather
  than request-scoped — stop and report; this spec's design assumes
  request-scoped recovery is sufficient because the temp-file pattern
  already prevents a crash *during* step 5 from corrupting the live file,
  and a crash *between* 5 and 6 leaving YAML/DB briefly divergent until
  the next successful mutation is judged acceptable, but this judgment
  should be confirmed, not assumed silently correct.
- If the chosen home for the reconciliation-required marker (new table
  vs. reusing `workflow_runs`) turns out to need Phase 4a's migration to
  have landed first and Phase 4a isn't done yet — stop and report the
  dependency rather than either blocking on it silently or picking the
  new-table option purely to avoid coordination.

## Done criteria

- [ ] `sources.yaml` writes are atomic (temp file + `os.replace`) under
      every mutation route, proven by a test simulating a mid-write
      failure and asserting the original file is untouched.
- [ ] A documented process/file lock serializes concurrent mutation
      attempts under the single-writer assumption; the assumption itself
      is written down in an active doc, not just in this plan file.
- [ ] A DB-sync failure after a successful YAML write restores the prior
      YAML; if the restore itself fails, a `reconciliation_required` state
      is persisted and surfaced, never silently dropped.
- [ ] `GET /v1/admin/sources` composes one catalog read and one batched DB
      query — no per-source loop.
- [ ] Every existing behavior the current tests assert (create defaults,
      update merge-preserve, delete removes both sides, unknown-id 404,
      validation 422) still holds under the new mechanism.
