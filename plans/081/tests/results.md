# Documentation audit evidence

Status: In progress — first reconciliation pass complete; audit scope is large
(477 inventoried documents across both repos) and this pass focused on the
highest-authority/highest-traffic governing docs, not an exhaustive read of
every historical or leaf document. See "Remaining for a future session" below.

Documentation-only audit; no runtime code, tests, or production behavior changed.
Plan 080 (`plans/080/`) and `tests/property/` are owned by a concurrent agent and
were not touched. `data/exports/latest_articles.json` and
`news_collector/logic/workflows/pipeline_e2e.py` had pre-existing uncommitted
changes from unrelated work and were left untouched.

## Method

1. Read `plans/081/spec.md`, the existing `tests/inventory.json` (477 docs,
   both repos, already categorized) and this file's prior placeholder.
2. Read backend `AGENTS.md` and `docs/AGENTS.md` in full (change matrix,
   spec-driven workflow, review checklist) before editing anything.
3. Ran the automated baseline checks first to establish what tooling already
   catches, then focused manual review on docs those checks don't cover
   (narrative claims, index completeness, duplication, cross-references).
4. Read both repos' `docs/SOURCE_OF_TRUTH.md` (documentation authority
   chains and fact-ownership tables), then `docs/ARCHITECTURE.md`,
   `docs/PIPELINE_CONTRACTS.md`, `docs/PRODUCT_FLOW.md`, `docs/ci.md`,
   `docs/RUNBOOK_LOCAL_DEV.md`, `docs/INDEX.md`, `context/CONTRACTS.md`,
   `context/CURRENT_STATE.md`, `context/INVARIANTS.md`, both repos'
   `README.md`/`CONTRIBUTING.md`, frontend `AGENTS.md`/`docs/ARCHITECTURE.md`,
   `docs/tagging.md`, `docs/webhook-integration.md`, `docs/DEPLOYMENT_SECURITY_HEADERS.md`,
   `docs/checklists/SEO_CHECKLIST.md`, `docs/EDITORIAL.md`, and
   `article_images_audit.md` — cross-checking specific claims (file paths,
   script names, workflow job names, contract field references) against the
   actual source tree with targeted `ls`/`grep`/existence checks rather than
   trusting prose.
5. Cross-checked the sealed cross-repo schema contract: frontend
   `src/content.config.ts` vs backend `news_collector/contracts/frontend_schema.py`
   via the repos' own `npm run check:contract-sync` tool (strict mode) rather
   than manual diffing, since that tool already does the real type/constraint
   comparison the docs describe.
6. Edited only where a concrete drift or defect was verified against code;
   left ADRs, audits, migration docs, changelogs and other historical
   material untouched per both repos' `docs/SOURCE_OF_TRUTH.md` historical-
   boundary rules.

## Findings

### Fixed

1. **Frontend `AGENTS.md` had a stale tool-memory dump baked into the binding
   governance file.** A `<claude-mem-context>` block (dated 2026-04-18,
   unrelated project-history bullets) was committed inside the file, after
   the "Final Authority" section — verified present in `git show HEAD:AGENTS.md`,
   not a Read-time artifact. This is noise inside a document whose stated
   purpose is "engineering governance document... not a style guide." Removed
   the block; the rest of the file is unchanged. (`noticiencias/AGENTS.md`)
   Searched both repos for the same pattern (`claude-mem-context`,
   `recent context`) — the only other hits are the tool's own intentional
   placeholder files (`.agent/rules/claude-mem-context.md`,
   `.github/copilot-instructions.md`), which are correctly empty templates
   and were left alone.

2. **Backend `docs/INDEX.md` ADR table was missing half the ADRs that exist
   in the repo.** `docs/adr/` has 8 numbered ADRs (0001–0008); the index
   table listed only 0001, 0002, 0003 and 0005. ADR-0004 (curated enrichment
   registry spike), 0006 (durable workflow lifecycle state), 0007 (generate
   contracts instead of hand-maintained parsers) and 0008 (harden the
   two-repo boundary) were absent, even though all three "Proposed"-status
   ADRs (0006–0008) directly document architecture referenced elsewhere in
   currently-active docs (e.g. `docs/PIPELINE_CONTRACTS.md`'s Plan 060
   material). Since `docs/INDEX.md`'s stated job is "find the right document
   quickly," and ADRs are explicitly historical evidence (not to be rewritten
   for content), the fix was additive: added the 4 missing rows with brief,
   accurate one-line descriptions. Verified each file still exists at the
   claimed path. (`noticiencias_news_collector/docs/INDEX.md`)

3. **Backend `docs/ci.md` omitted an entire active CI workflow.**
   `.github/workflows/publication-smoke.yml` (added 2026-05-08, still present
   and path-triggered on `contracts/frontend_schema.py`,
   `contracts/publication_validation.py`, `logic/workflows/**` and
   `components/publishing/**` changes) was not mentioned anywhere in
   `docs/ci.md`, including its "Other Active Workflows" section, which is
   presented as an enumeration of workflows beyond the primary `ci.yml`/`quality.yml`
   gates. A contributor touching contract or publishing code would not learn
   from `docs/ci.md` that this gate exists and would fire on their PR. Added
   a short, accurate entry under "Architecture And Contract Focus" describing
   its trigger paths and what it does (sparse-checks out the sibling frontend
   repo and runs `scripts/validate_frontend_publication.py`). Verified job
   names in `.github/workflows/ci.yml` still match the doc's existing table
   exactly (`lint`, `type`, `config`, `contract-parity`, `test`, `coverage`,
   `perf`, `healthcheck`, `build-artifacts`, `update-ci-badge`) — no drift
   there. (`noticiencias_news_collector/docs/ci.md`)

4. **Frontend `README.md` listed two historical audit documents under
   "Governance Docs" without labeling them historical**, unlike (a) the
   backend's own `README.md`, which lists its equivalent historical audit/
   backlog docs with explicit "historical" wording in the same section, and
   (b) the frontend's own `docs/SOURCE_OF_TRUTH.md`, which explicitly places
   `docs/audits/**` and root-level one-off notes under "Non-Authoritative
   Material." Relabeled the two entries (`docs/audits/2026-04-source-of-truth-audit.md`,
   `docs/backlog/source-of-truth-backlog.md`) to say "historical" and to
   point at `plans/README.md` for current status, matching the backend's
   phrasing pattern and removing the implication that they are current
   governance. (`noticiencias/README.md`)

5. **Backend `docs/AGENTS.md`'s own `Scope:` header was a stale, non-portable
   absolute path.** Line 5 read
   `Scope: /home/carlos/VS_Code_Projects/noticiencias/noticiencias_news_collector`
   — missing the real `products/` path segment (the actual clone lives at
   `/home/carlos/VS_Code_Projects/products/noticiencias/noticiencias_news_collector`)
   and, independent of that, a machine-specific absolute path in a document
   the spec's acceptance criteria explicitly require to use "portable
   repository-relative paths." This is on the single highest-authority backend
   governance doc, in its second line. Notably, an archived plan
   (`plans/archive/043-repair-active-documentation.md`) explicitly called out
   fixing exactly this class of problem ("Use repository-relative Markdown
   links, not `/home/carlos/...` absolute paths") — this instance either
   regressed after that plan or was missed by it. Fixed by replacing the
   literal path with `Scope: this repository (\`noticiencias_news_collector\`)`.
   Swept both repos for the same pattern afterward
   (`grep -rn "/home/carlos" --include="*.md"`, excluding archived plans/audits,
   which are historical and legitimately reference paths as investigation
   evidence): no other active-doc hits in either repo.

### Reclassified (inventory only, no content edit)

6. `noticiencias/article_images_audit.md` was categorized
   `current-guidance-candidate` in `tests/inventory.json` but its content is a
   closed root-cause investigation (all findings marked "Fixed" with commit
   hashes, e.g. `321b67e`, `b3dda74`). Reclassified to
   `historical-proposal-or-decision` with a note explaining why. Content left
   untouched — it reads correctly as a closed post-mortem and per the
   historical-boundary rule should not be rewritten to match current state.

### Checked, no drift found (evidence, not exhaustive)

- Both repos' `docs/SOURCE_OF_TRUTH.md`: every code-owned-authority file
  path referenced (`news_collector/serving/webhook_handler.py`,
  `refinery_engine.py`, `collection_run_workflow.py`,
  `publication_run_workflow.py`, `storage/database.py`,
  `fly-serving.toml`, `fly-tunnel.toml`; frontend `social-manifest.json.ts`,
  `dist-sanity.js`, `permalinks.ts`, `blog.ts`, `Metadata.astro`,
  `search.json.js`, `build-search-index.ts`, `workers/src/handlers/report.ts`,
  `workers/src/utils/validate.ts`) exists at the claimed path.
- `docs/ARCHITECTURE.md`, `docs/PIPELINE_CONTRACTS.md`, `docs/PRODUCT_FLOW.md`,
  `docs/RUNBOOK_LOCAL_DEV.md`, `context/CONTRACTS.md`, `context/CURRENT_STATE.md`,
  `context/INVARIANTS.md`, backend `README.md`/`CONTRIBUTING.md`: claims
  read as accurate against current code and the Makefile; commands referenced
  (`make lint`, `make admin`, `make config-docs-check`, `.placeholder-audit.yaml`,
  `scripts/score_delta.py`, `tests/data/scoring_golden.json`, etc.) all exist.
  These docs already carry careful "current vs. desired" framing (e.g.
  Publication identity fallback framed as bounded compatibility debt, not
  perfect determinism) consistent with the spec's requirement not to describe
  desired architecture as already shipped.
- The `npm run typecheck` references flagged in the task brief
  (`docs/report-pipeline-setup.md`, `docs/supported-dependency-matrix.md`)
  are already correctly scoped to `workers/` (confirmed against
  `workers/package.json`'s own `typecheck` script) — this was already fixed
  by frontend commit `fb94518` ("fix: scope workers-only npm scripts in
  doc-drift check") before this session started. No further action needed.
- Frontend `AGENTS.md`, `docs/ARCHITECTURE.md`, `docs/tagging.md`,
  `docs/webhook-integration.md`, `docs/DEPLOYMENT_SECURITY_HEADERS.md`,
  `docs/checklists/SEO_CHECKLIST.md`, `docs/EDITORIAL.md`, `CONTRIBUTING.md`:
  workflow names (`perf-monitor.yml`'s monthly 09:37 UTC cron,
  `content-guard.yml`'s snapshot fallback), scripts
  (`backend-notify.js`, `pre-publish-gate.js`, `post-publish-callback.js`)
  and the `.contract-snapshots/frontend_schema.snapshot.json` file all exist
  and match the described behavior.
- Cross-repo contract: `npm run check:contract-sync --strict` reports full
  parity with one documented, intentional divergence (`AstroPost.date`:
  Python `date|date` union vs. TypeScript `date`, allowed by both sides'
  docs). No undocumented contract drift.

## Remaining for a future session

This pass covered the top-level governance/architecture/CI/runbook docs and
both repos' README/CONTRIBUTING files, plus a handful of docs called out
by name in the task brief. It did **not** do a full line-by-line read of
every backend leaf doc still categorized `current-guidance-candidate` in
`tests/inventory.json` — notably `docs/testing.md`, `docs/runbook.md`,
`docs/collector_runbook.md`, `docs/operations.md`, `docs/database_deployment.md`,
`docs/security.md`, `docs/api_examples.md`, `docs/EDITORIAL_MODES.md`,
`docs/editorial_quality_system.md`, `docs/contracts_inventory.md`,
`docs/common_output_format.md`, `docs/faq.md`, `docs/fixtures.md`,
`docs/performance_baselines.md`, `docs/placeholder_policy.md`,
`docs/release-checklist.md`, `docs/release_notes.md`,
`docs/security_removal_plan.md`, `docs/runbooks/healthcheck.md`,
`docs/strategic_features.md`, `docs/tools_audit_issues.md`, `perf/bench.md`,
`scripts/debugging/README.md`, `news_collector/taxonomy/README.md`, and the
frontend's `docs/EDITORIAL_VOICE.md`, `docs/report-pipeline-setup.md` (only
the flagged section was checked), `docs/supported-dependency-matrix.md`
(same), and the `context/modules/*` per-module notes (validated only via
`make context-validate`, which passed, not read individually). A future
session should sweep these with the same "read claim, verify against code"
method, though none surfaced as suspicious during the inventory categorization
pass and both repos' automated doc-drift/context-validate gates already
cover their path/command/invariant references.

## Validation run

Backend:

```
.venv/bin/python scripts/check_doc_drift.py   # OK - 14 docs checked, all paths/commands/invariants verified (before AND after edits)
.venv/bin/python scripts/validate_plans_ledger.py   # validate_plans_ledger: OK
make context-validate                          # Context validation passed.
make config-docs-check                          # Environment ready (no diff)
```

Frontend:

```
npm run check:doc-drift   # exit 0 — "OK — 13 docs checked, all paths, commands,
                           # invariants, and authority references verified."
npm run check:contract-sync -- --strict ...   # [contract-sync] OK — full parity confirmed
                                                # (1 documented divergence, tolerated)
```

**`npm run validate:content` (aggregate command) now also exits 1, and this too
is environmental/concurrent, not caused by this plan's edits.** Its first run
during this session (before any concurrent-work files had appeared) was clean:
0 errors, 0 warnings, 6 hints, 248 files. Re-run just now at the end of this
session it reports 2 TypeScript errors, in a **new untracked file**,
`tests/social/buffer.test.ts` (`ts(2741)` and `ts(2339)`, both type-shape
mismatches unrelated to any documentation content). That file, like
`scripts/social/providers/buffer.js` above, is untracked, was not created or
edited by this session, and belongs to the same concurrent, in-progress
social-distribution work. It is out of this plan's scope to fix (documentation-
only; not this session's file). The doc-drift check specifically relevant to
this plan's edits — `npm run check:doc-drift` — was re-run directly and is
green, both before and after this observation.

**`npm run lint` (the aggregate frontend command) currently exits 1 — this is
an environmental failure unrelated to this plan's edits, not a regression from
them.** Root cause: `prettier --check .` (the last step in `lint`) flags
`scripts/social/providers/buffer.js`, an **untracked** file (`git status
--short` shows `?? scripts/social/providers/buffer.js`) that this session did
not create or touch — it belongs to unrelated, concurrent, in-progress
social-distribution work (see project memory: "Sigue paquete 7"). This
session's own first `npm run lint` run, taken at the very start before any
edits, printed a clean `prettier --check .` ("All matched files use Prettier
code style!"), so the file was not present (or not yet flagged) at that point
— it appeared mid-session from that concurrent work, not before this session
started. Either way it is not this plan's file to fix (documentation-only
scope; touching another in-flight agent's untracked file is out of bounds).
`check:doc-drift`, the specific gate this plan's edits touch, passes on its
own (confirmed above by running it directly). One earlier iteration of this
plan's own edit *did* cause a genuine `check:doc-drift` failure
(`README.md:69` referenced `plans/README.md` as a bare inline-code path,
which the checker correctly flagged as not existing in this repo) — that was
found by review and fixed by rewriting the reference as a proper
`../noticiencias_news_collector/plans/README.md` relative link; re-verified
green afterward. That earlier, self-caused failure is not the same as the
`buffer.js` prettier failure, which is not this plan's to fix (out of scope:
documentation-only, no code edits).

No runtime build or test suite was run beyond what the commands above already
execute (`astro check`/`astro sync` as part of `validate:content`), per the
spec's "no runtime build/tests required solely for backend prose edits" note
— all five edited files (`docs/INDEX.md`, `docs/ci.md`,
`noticiencias/AGENTS.md`, `noticiencias/README.md`, plus this plan's own
`tests/inventory.json`/`tests/results.md`/`todo.md`) are Markdown/JSON.

## Review (backend `docs/AGENTS.md` §0.1(d))

Backend governance requires a fresh sub-agent review of `spec.md` vs. the
current implementation after a major edit phase. This was requested via the
Agent tool (`review spec.md and the current diff for gaps`) after the first
edit pass. The review returned **FAIL** on one concrete, verified defect: the
`README.md:69` broken-path regression described above (frontend `npm run
lint`/`check:doc-drift` was genuinely red at that point, contradicting what
had been recorded), plus a secondary accuracy gap in the `docs/ci.md`
`publication-smoke.yml` entry (missing path prefixes and two of six trigger
paths). Both were fixed and re-verified (see above and the `docs/ci.md` diff).
The review confirmed everything else — ADR table additions, scope containment
(no runtime/plans-080/tests-property files touched), and the frontend
`AGENTS.md` cleanup — as accurate. This results.md was updated after the fix,
so the record above reflects the post-review, re-verified state, not the
state the reviewer initially failed.

## Limitations (honest)

- This is a large, partly subjective task ("drift," "duplication," "misleading
  guarantee") over hundreds of files; a single pass cannot certify zero
  remaining drift. The five fixes plus one reclassification above are the
  concrete, verified findings from this pass — not a claim that these are the
  only issues in the corpus.
- I did not run `make quality`, `make test`, `make test-contracts`,
  `make test-boundaries`, or any frontend build/e2e suite — the spec says
  no runtime build/tests are required solely for backend prose edits, and
  none of the edits touch code, config, or contracts.
- The sub-agent review step (previous section) is a governance requirement
  I can request but cannot self-certify as sufficient; treat its recorded
  outcome as the actual evidence, not this paragraph.
- The frontend `AGENTS.md` `<claude-mem-context>` block removal (finding 1)
  is a content edit, not a configuration change to whatever tool injected it.
  If that tool re-appends the same kind of block on a future session (as it
  appears to do for repos lacking the backend's dedicated placeholder files,
  `.agent/rules/claude-mem-context.md` / `.github/copilot-instructions.md`),
  the removal is not guaranteed to stay permanent and may need repeating.
  This plan did not add a frontend placeholder file to pre-empt that, since
  doing so was not verified as load-bearing or requested by the spec.
