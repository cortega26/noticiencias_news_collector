# Plan 049: Spike a versioned publication feed — spec

## Outcome: DONE (spike)

Decision-only spike: a use-case analysis plus a synthetic contract
prototype. No production storage, workflow, or content was changed; the
direct Git/PR publication path remains the production control. The
spike's recommendation (DO NOT BUILD) is supported by a concrete
per-use-case comparison against the current Git/PR path and by named
simpler alternatives for the only prioritized gap.

## What was in scope for this pass

Per the plan's Steps 1-2 and 6 (decision-driving use cases, minimal
immutable contract, build/no-build decision) — everything a spike can
prove without touching production:

1. **Step 1 (use-case analysis)** — done: 8 use cases evaluated against
   the current Git/PR path, documented in
   `docs/spikes/versioned-publication-feed.md` § "Decision-driving use
   cases".
2. **Step 2 (minimal immutable contract)** — done: `FeedRevision v1`
   documented in the same file, § "Minimal immutable contract".
3. **Step 6 (build/no-build decision)** — done: DO NOT BUILD
   recommendation with rationale, simpler alternatives, dependencies,
   and revisit conditions, § "Build/no-build decision".
4. **Contract prototype** — `tests/spikes/test_publication_feed.py`
   (17 synthetic tests, all passing — count verified by running pytest,
   not assumed from the ledger).

## Goals actually achieved

1. **`docs/spikes/versioned-publication-feed.md`** (85 lines) contains
   all three claimed sections:
   - **Use-case analysis**: exactly 8 use cases (verified by counting the
     table rows): failed PR recovery, multi-article atomicity,
     correction/tombstone propagation, reproducible rollback, consumer
     decoupling, audit history, publish latency, future consumers — each
     with a "Feed would help?" verdict and a note on the current Git/PR
     path. 3 prioritized (atomicity, tombstones, failed-PR recovery);
     named consumers/operators stated (single frontend Astro consumer).
   - **Minimal immutable contract `FeedRevision v1`**: `feed_version`,
     monotonic `revision`, `parent`, `producer_commit`, `generated_at`,
     `operation` (upsert|tombstone), `refinery_id`, `canonical_slug`,
     SHA-256 `content_hash`, frontmatter/body (no MDX execution),
     assets, `prior_revision`, `batch_hash`; canonical serialization
     (JSON sorted keys, no trailing whitespace); ordering by revision;
     idempotency rule (same `refinery_id` + `content_hash` = duplicate,
     skipped); tombstone requires a prior upsert.
   - **Decision**: DO NOT BUILD — justified by Git +
     `refinery_manifest.json` already providing versioning, audit
     history, and rollback for the single consumer; the only prioritized
     gap (multi-article atomicity) addressed more simply via a batch ID
     in the existing PR flow; tombstones implementable as a frontmatter
     field (`status: retracted`); feed operational cost (storage,
     compaction, signing, consumer sync) named; explicit revisit
     conditions (second consumer appears, or batch-PR proves
     insufficient). Not vague or generic.
2. **`tests/spikes/test_publication_feed.py`** — 17 tests, substantive,
   not trivial:
   - contract validation: valid upsert, unknown feed version rejected,
     non-monotonic revision rejected, duplicate (same id + hash)
     rejected, tombstone without prior upsert rejected, path-traversal
     slug rejected;
   - determinism: canonical JSON keys sorted, same revision → same JSON,
     replay is deterministic across calls;
   - replay/rollback: rollback_to returns prior state, tombstone marks
     current state, correction with prior_revision, rollback to zero,
     nonexistent id returns None, double tombstone rejected as duplicate,
     content-hash changes with body, empty store replay.
   Run: `.venv/bin/python -m pytest tests/spikes/test_publication_feed.py -v`
   → **17 passed**.

## What was NOT touched

- No production storage, workflow, or content changed:
  `git show --stat d208200` (the spike's own commit) touches exactly two
  files — `docs/spikes/versioned-publication-feed.md` and
  `tests/spikes/test_publication_feed.py`.
- Later edge-case hardening in `e73377f` extended the spike test file
  (+5 tests) alongside plan 017's unrelated UI-slice changes; it added no
  production code for this spike.
- The Git/PR publication path (`TargetRepoWriter`, `RefineryEngine`,
  `PROrchestrator`) is byte-identical to before this spike.

## Verification

- [x] `docs/spikes/versioned-publication-feed.md` read end-to-end: all 3
      claimed sections present and substantive.
- [x] `pytest tests/spikes/test_publication_feed.py -v` → 17 passed
      (counted from test output, not the ledger).
- [x] 8 use-case rows counted directly from the document's table.
- [x] `git show --stat d208200` confirms docs+tests only — no production
      storage touched.
