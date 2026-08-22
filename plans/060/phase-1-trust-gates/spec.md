# Plan 060 / Phase 1: Close low-cost security, CI, dashboard, and docs gaps

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in "STOP conditions" occurs, stop and report — do not
> improvise. This phase spans **two sibling repositories** that live under the
> same parent directory:
>
> - **Backend** = `noticiencias_news_collector/` (this repo; also the home of
>   the master plan at `plans/060/spec.md` and `plans/060/todo.md`)
> - **Frontend** = `noticiencias/` (sibling directory — same parent as backend)
>
> Unlike Phase 0, this phase's backend and frontend work items are fully
> independent of each other (no shared ADR numbering, no shared fixture
> corpus) — if dispatched into a worktree of only one repo, complete only that
> repo's steps below and report which half still needs a separate dispatch.
>
> When done, update the status row for **this phase** in `plans/060/todo.md`
> (check off the five "Phase 1" boxes under "Wave A") — unless a reviewer
> dispatched you and told you they maintain the index.
>
> **Drift check (run first, in each repo you touch)**:
> `git diff --stat 4153db2..HEAD -- .github/workflows/quality.yml docs/ARCHITECTURE.md docs/PIPELINE_CONTRACTS.md scripts/check_doc_drift.py news_collector/logic/workflows/publication_identity.py` (backend)
> `git diff --stat ee65eea..HEAD -- package.json scripts/check-search-budget.js scripts/check-contract-sync.js .github/workflows/content-guard.yml src/pages/admin/dashboard.astro CONTRIBUTING.md` (frontend)
> If either reports changes, compare the "Current state" excerpts below
> against the live files before proceeding; on a mismatch, treat it as a STOP
> condition — this plan's evidence baseline may be stale.
>
> Frontend also currently has two **unrelated, pre-existing uncommitted
> changes** at dispatch time: `docs/adr/0005-durable-workflow-lifecycle-state.md`
> and `docs/adr/0007-harden-two-repo-boundary-before-reconsidering-consolidation.md`
> (two-line relative-path fixes from Phase 0's post-merge cleanup). Leave them
> exactly as they are — do not commit them as part of this phase's work, and
> do not revert them.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: LOW (every fix here is either additive verification, a doc
  correction, or a display-state change — no schema, migration, or public API
  changes)
- **Depends on**: `plans/060/phase-0-baseline/` (DONE — merged; this phase
  does not actually consume anything Phase 0 produced, but follows it in the
  master plan's wave ordering)
- **Category**: security / tech-debt / docs (Wave A, "immediate trust gates")
- **Planned at**: backend commit `4153db2`, frontend commit `ee65eea`,
  2026-08-22
- **Parent plan**: `plans/060/spec.md`, section "Phase 1: Close low-cost
  security, CI, dashboard, and docs gaps" — you do not need to read the rest
  of that file; everything required is inlined below. **Do not edit
  `plans/060/spec.md` itself for any reason** — see Scope.

## Why this matters

Six independent, low-risk gaps sit between the current codebase and what its
own CI/docs/dashboard claim about it. None of them require the invasive
schema or workflow changes later phases bring — they're the kind of thing
that erodes trust in the rest of the program if left alongside it: a security
scan step that trusts an unverified binary download, operational docs that
describe removed behavior, a dashboard that shows green without evidence, and
a "mirrors CI" claim that overstates what it actually checks. Fixing these
first, before the riskier phases, is what "immediate trust gates" means in
the master plan's wave ordering.

## Current state

### Backend item 1 — unverified Gitleaks binary download

`.github/workflows/quality.yml:44-48`:

```yaml
      - name: Install Gitleaks
        run: |
          GITLEAKS_VERSION="8.18.1"
          curl -sSL "https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}/gitleaks_${GITLEAKS_VERSION}_linux_x64.tar.gz" \
            | tar -xz -C /usr/local/bin gitleaks
```

The version is already pinned (8.18.1), but the downloaded archive is piped
directly into `tar -xz -C /usr/local/bin` with no integrity check at all — a
corrupted, truncated, or MITM'd download is extracted and executed with no
warning. **Verified for this plan** (read-only checks, not part of the
codebase): `gh release view v8.18.1 --repo gitleaks/gitleaks --json assets`
confirms both `gitleaks_8.18.1_linux_x64.tar.gz` and
`gitleaks_8.18.1_checksums.txt` exist as release assets, and the checksums
file's line for the Linux binary reads exactly:

```
3e157a26081e296d4cb94ef0d87441c9afc5f392cb02957656dd5cfeb7aaf6c9  gitleaks_8.18.1_linux_x64.tar.gz
```

(two spaces between hash and filename — standard `sha256sum`-compatible
format). Do not hardcode this hash into the workflow — fetch the checksums
file fresh each run and verify the downloaded archive against the line
matching its own filename. This is the standard "publisher-provided
checksum" pattern: it doesn't defend against a compromised GitHub release
(same trust boundary as the binary itself), but it does catch corruption,
truncation, and a large class of MITM/CDN-substitution failures that the
current pipe-to-tar has zero defense against. That is what the master plan's
Phase 1 bullet ("verify the publisher-provided SHA-256 checksum before
extraction") asks for.

### Backend item 2 — stale publication-date fallback docs (plan 058 already removed the fallback; docs still describe it)

Plan 058 (archived, `plans/archive/058-deterministic-publication-date/`,
merged 2026-08-13 at commit `7c7b180`) removed the non-deterministic
"current date as last resort" fallback from publication identity resolution
and replaced it with a hard failure. The current, authoritative behavior —
`news_collector/logic/workflows/publication_identity.py:6-9` (module
docstring, unchanged by this phase):

```
- Priority 1: DB canonical slug (immutable identity lock)
- Priority 2: FS scan via TargetRepoWriter manifest (legacy recovery + self-heal)
- Priority 3: Creation mode — derive deterministically from published_date,
  else collected_date; quarantine (UndatedArticleError) when neither exists.
```

Two active docs still describe the old, removed behavior:

**`docs/PIPELINE_CONTRACTS.md:63-79`** (current, stale text):

```markdown
### Current Identity Reuse Order

`RefineryEngine` currently resolves publication identity in this order:

1. database `canonical_slug`
2. existing frontend file or sidecar manifest
3. `published_date`
4. `collected_date`
5. current date as last resort

The final two fallback steps are compatibility debt. They are not the desired end state for immutable identity.
```

Replace it with exactly:

```markdown
### Current Identity Reuse Order

`RefineryEngine` currently resolves publication identity in this order:

1. database `canonical_slug`
2. existing frontend file or sidecar manifest
3. `published_date`
4. `collected_date`
5. quarantine (`UndatedArticleError`) when neither date exists

Plan 058 (2026-08-13) removed the runtime-clock fallback: an article with
neither `published_date` nor `collected_date` is no longer silently dated
with the current date — it fails deterministically and is quarantined for
human review. The two remaining fallback steps (`published_date` →
`collected_date`) are compatibility debt, not the desired end state for
immutable identity, but they no longer include a non-deterministic path.
```

**`docs/ARCHITECTURE.md:151`** (current, stale text):

```
The workflow reuses database or file-based identity when available, but it still falls back to `collected_date` and then current date when source dates are missing. Documentation should treat that as bounded compatibility debt, not as perfect determinism.
```

Replace it with exactly:

```
The workflow reuses database or file-based identity when available, but it still falls back to `collected_date` when `published_date` is missing, and quarantines the article (`UndatedArticleError`) rather than inventing a date when neither exists (plan 058). Documentation should treat the `published_date`/`collected_date` fallback as bounded compatibility debt, not as perfect determinism — but there is no remaining non-deterministic path.
```

**Extend the doc-drift invariant checker** so this specific regression
(reintroducing "current date as last resort" language anywhere in an active
doc) fails CI automatically, the same way `stale_schema_path` already does
for the frontend schema path. `scripts/check_doc_drift.py:356-392` is the
`check_invariants()` function — the existing pattern (excerpted, do not
copy verbatim, this is illustrative of the style to match):

```python
def check_invariants(
    line: str, doc: str, line_no: int, site_host: str | None
) -> list[dict]:
    found: list[dict] = []
    if "`src/content/config.ts`" in line:
        found.append({
            "doc": doc,
            "type": "stale_schema_path",
            "ref": "src/content/config.ts",
            "line": line_no,
            "message": "expected `src/content.config.ts` (frontend schema authority)",
        })
    ...
```

Add a new check to this same function, matching the same simple
string-containment style (not a regex, consistent with the schema-path and
site-host checks): **two separate literal-substring checks**, one per stale
phrase, each producing type `stale_publication_date_fallback` — one pattern
will not catch both phrases (they're worded differently in the two docs):

```python
    if "current date as last resort" in line:
        found.append({
            "doc": doc,
            "type": "stale_publication_date_fallback",
            "ref": "current date as last resort",
            "line": line_no,
            "message": "plan 058 removed the runtime-clock fallback — publication identity now quarantines (UndatedArticleError) instead of falling back to the current date",
        })
    if "current date when source dates are missing" in line:
        found.append({
            "doc": doc,
            "type": "stale_publication_date_fallback",
            "ref": "current date when source dates are missing",
            "line": line_no,
            "message": "plan 058 removed the runtime-clock fallback — publication identity now quarantines (UndatedArticleError) instead of falling back to the current date",
        })
```

**Sequencing matters and is not optional**: `tests/unit/docs/test_check_doc_drift.py::test_live_repo_docs_pass`
(line 153) runs the live doc-drift checker against the real backend docs with
zero tolerance for violations. If you add the new invariant check *before*
fixing the two docs above, that test goes red between commits. **Fix both
docs, add the invariant check, and add its fixture test in one commit** — the
intermediate state (invariant added, docs not yet fixed) is not a valid
commit boundary.

**Fixture test** — model `test_flags_stale_schema_path` (`tests/unit/docs/test_check_doc_drift.py:88-96`):

```python
def test_flags_stale_schema_path():
    combined, exit_code = run_check(
        str(FIXTURES / "stale"),
        ["README.md"],
    )
    assert exit_code == 1, combined
    assert "stale declared claim" in combined
    assert "src/content/config.ts" in combined
    assert "src/content.config.ts" in combined
```

`tests/fixtures/doc-drift/stale/README.md` already exists and already
contains lines that trigger the schema-path and site-host checks (three
lines total currently: schema path, site host, and one more — read the file
first). Add one more line to that same file containing the literal phrase
`current date as last resort` (either stale phrase works; pick one), and
write `test_flags_stale_publication_date_fallback` in
`tests/unit/docs/test_check_doc_drift.py` following the exact pattern above
(no other existing test in that file asserts an exact violation count, only
`exit_code == 1` and substring presence — adding a fourth stale line to the
shared fixture file does not break `test_flags_stale_schema_path` or
`test_flags_stale_site_host_with_sibling`, confirmed by reading both).

### Frontend item 3 — search budget script exists but isn't wired into anything

`scripts/check-search-budget.js` (complete, working, already reads a
`search.json` from a `dist/`-relative path argument, checks JSON validity,
required keys, no raw `content` field, unique URLs, and a 150KB gzip
ceiling) exists but has **zero callers**: no `package.json` script entry, no
CI step, no test file. `content-guard.yml:141-145` is the only place in CI
that has a fresh `dist/` to check against:

```yaml
      - name: 🏗️ Build Frontend
        run: npm run build
      - name: 🧪 Dist Sanity
        run: npm run test:dist
```

**Decisions for this step** (made here so the executor doesn't have to
guess):

1. Add `"check:search-budget": "node scripts/check-search-budget.js"` to
   `package.json`'s `scripts` block (near the other `check:*` entries) — the
   script already defaults its path argument to `dist`, matching where
   `npm run build` writes output, so no argument is needed.
2. In `content-guard.yml`, add a new step **immediately after** "🧪 Dist
   Sanity" (after line 145): a separate step named `📏 Search Budget` running
   `npm run check:search-budget`. Use a separate CI step, not an addition
   inside `test:dist`'s own script — a distinct step gives a distinct
   pass/fail signal in the GitHub Actions UI instead of burying a budget
   failure inside dist-sanity's output.
3. Also add `npm run check:search-budget` to the `verify:ci` script in
   `package.json` (current definition, exact):
   ```json
   "verify:ci": "npm run lint && npm run validate:content && npm run build && npm run test:dist && npm run test:audit && CI=1 npm run test:e2e && npm run check:contract-sync"
   ```
   Insert it right after `npm run test:dist` (same relative position as in
   CI), so local `verify:ci` runs and CI stay in the same order. This
   directly matters for item 6 below — you are already correcting
   `CONTRIBUTING.md`'s description of what `verify:ci` covers in that step,
   so make that edit *after* this one, in the same pass, so the doc reflects
   the final command list once, not twice.

**Test fixtures** (`tests/contract-sync.test.ts` is the pattern to follow —
`execSync` against the CLI script, asserting on exit code and message
content, not a refactor of the script into an importable function): write
`tests/check-search-budget.test.ts` with two cases, both building a fixture
`dist/search.json` in a temp directory (`fs.mkdtempSync`, cleaned up in
`afterEach`, same pattern as `tests/r2-image-quota-guard.test.ts`):

- **Passing case**: a small, valid `search.json` (a handful of entries, well
  under the ceiling) — assert exit code 0 and the `"✅ search artifact is
  valid"` message.
- **Oversized case** — read the script's exact guard logic first
  (`scripts/check-search-budget.js`, the last two checks before the success
  path) before building this fixture: there are **two separate size checks**,
  the 150KB gzip ceiling *and* a second heuristic
  (`raw.length > 500 * 1024 && urls.length < 10`) that flags a "bloated
  fixture" shape (huge raw size, suspiciously few entries). **Correction**:
  the gzip-ceiling check actually runs first in the live file, the bloat
  heuristic second — the opposite of what an earlier draft of this plan
  claimed. Either way, do not rely on check order: a fixture built by
  inflating one entry's text to a huge
  size will trip the second guard, not the first — and the test would then
  be passing for the wrong reason (a coincidentally-different failure
  message). Build the oversized fixture with **many entries** (at least
  15-20, well over the second guard's `< 10` threshold) each containing a
  moderate amount of unique, poorly-compressing text (e.g. distinct
  index-numbered strings — avoid highly repetitive text, which gzip
  compresses too well to cross 150KB), so the fixture exceeds the gzip
  ceiling on its own merits without ever tripping the bloat heuristic.
  Generate this programmatically inside the test (a loop building N store
  entries), not as a large static file checked into the repo. Assert exit
  code 1 and that the failure message contains the specific text `exceeds`
  and `ceiling` (the script's actual message is
  `` `gzip size ${gzipped.length} exceeds ${GZIP_CEILING} ceiling` `` — assert
  on that, not just a generic non-zero exit code, so a future change to the
  bloat-heuristic message wouldn't silently make this test pass for the
  wrong reason again).

### Frontend item 4 — `check:contract-sync` and its CI paths don't use `--strict`

`package.json` (current, exact):

```json
"check:contract-sync": "node scripts/check-contract-sync.js ${BACKEND_SCHEMA_PATH:-../noticiencias_news_collector/news_collector/contracts/frontend_schema.py} src/content.config.ts"
```

`.github/workflows/content-guard.yml:73-82` (current, exact):

```yaml
          if [ -f "$LIVE_SCHEMA" ]; then
            echo "::notice::Using live backend schema from sparse checkout."
            BACKEND_SCHEMA_PATH="$LIVE_SCHEMA" npm run check:contract-sync
          elif [ -f "$SNAPSHOT" ]; then
            echo "::warning::Backend schema not available (fork/Dependabot?). Using committed snapshot."
            node scripts/check-contract-sync.js --snapshot "$SNAPSHOT" src/content.config.ts
          else
            echo "::error::Neither live backend schema nor snapshot found. Cannot verify contract parity."
            exit 1
          fi
```

Neither path uses `--strict`. **Verified for this plan** (both commands run
against the live repo, read-only, not part of the codebase): both already
pass cleanly in strict mode —

```
$ node scripts/check-contract-sync.js --strict "$BACKEND_SCHEMA_PATH" src/content.config.ts
[contract-sync] OK — full parity confirmed.
[contract-sync] 1 known divergence(s) tolerated:
  • AstroPost.date: Type mismatch: Python "union<date|date>" vs TypeScript "date" (allowed: Zod z.date() covers both; Pydantic explicitly allows both date and datetime)

$ node scripts/check-contract-sync.js --strict --snapshot .contract-snapshots/frontend_schema.snapshot.json src/content.config.ts
[contract-sync] OK — full parity confirmed.
[contract-sync] 1 known divergence(s) tolerated:
  • AstroPost.date: Type mismatch: Python "union<date|date>" vs TypeScript "date" (allowed: Zod z.date() covers both; Pydantic explicitly allows both date and datetime)
```

(`--strict` and `--snapshot` are independent flags parsed in the same loop,
`scripts/check-contract-sync.js:33-55` — they combine without special
handling.) Fix:

1. `package.json`: add `--strict` as the first argument in the
   `check:contract-sync` script string, before `${BACKEND_SCHEMA_PATH:-...}`.
2. `content-guard.yml:78`: change
   `node scripts/check-contract-sync.js --snapshot "$SNAPSHOT" src/content.config.ts`
   to
   `node scripts/check-contract-sync.js --strict --snapshot "$SNAPSHOT" src/content.config.ts`.
   (Line 75's `npm run check:contract-sync` picks up `--strict` automatically
   once the package.json script is fixed — no separate edit needed there.)
3. Also check `.github/workflows/sync-contract-snapshot.yml` for any other
   non-strict invocation of `check-contract-sync.js` — read the file first;
   if it invokes the script only in `--generate-snapshot` mode (which has no
   strict/non-strict distinction), no change is needed there. Do not add
   `--strict` to a `--generate-snapshot` invocation — the flag has no defined
   interaction with that mode in the script's own usage docstring and adding
   it would be scope creep beyond what this plan verified.

### Frontend item 5 — dashboard hard-coded pass states

`src/pages/admin/dashboard.astro:83-119` builds a `healthChecks` array from
`data/metrics/pipeline-metrics.json` (loaded at lines 10-20, `metrics`
variable). Three of the five checks already correctly derive `status` from
measured data (`metrics ? 'pass' : 'unknown'`, an editorial-gap computation,
and `images?.derivatives_available`). Two do not — **verified for this
plan**: `scripts/generate-metrics.js` (the generator of
`pipeline-metrics.json`) produces no hero-image or lint-status field at all
(`grep -n "hero\|lint" scripts/generate-metrics.js` returns nothing) — there
is no metric these two checks could honestly derive from today:

```
106:    status: 'pass' as const,     // "Imágenes hero" check, detail: 'Validado en CI'
118:    status: 'pass' as const,     // "Linting" check, detail: 'Validado en pre-commit y CI'
```

Fix: change both to `'unknown'`, matching the existing pattern used two
checks above them (`(metrics ? 'pass' : 'unknown') as 'pass' | 'unknown'`).
Update each `detail` string to explain why (e.g. `'Sin métrica medida —
verificar manualmente en CI'`) rather than leaving the old "Validado en
CI"/"Validado en pre-commit y CI" claims, which implied a live signal that
does not exist. Do **not** attempt to wire a real metric for these two checks
in this phase — that's new instrumentation work, out of scope for a
low-cost Phase 1 fix (the master plan's own acceptance criterion is "shows
only observed states," not "adds new observations").

### Frontend item 6 — `CONTRIBUTING.md` overstates what `npm run build` and `verify:ci` do

**`CONTRIBUTING.md:22`** (current, exact): `npm run build             #
production build (runs validate:content first)` — false. The actual script
(`package.json:11`, current, exact): `"build": "npm run
publish:image-derivatives && astro build"`. It does not run
`validate:content` (a separate, much larger script at `package.json:45` —
`check:runtime-artifacts`, `check:executable-content`,
`check:frontmatter-dates`, `check:hero-images`, `check:image-alt`,
`check:slug-quality`, `check:published-sidecars`, `check:image-extensions`,
`check:image-derivatives`, `check:content-quality`, `check:tags`,
`check:editorial-fields`, `astro sync`, `astro check`, `check:freeze` — 14
checks). `astro build` does perform Astro's own internal content-collection
Zod validation as a side effect of building, but that is not the same thing
as running the full `validate:content` pipeline.

**`CONTRIBUTING.md:29-33`** (current, exact) additionally claims:

```
   npm run verify:ci
   ```
   This runs lint, content validation, build, dist sanity, unit tests,
   browser tests, and the cross-repo contract sync in one pass — the same
   checks `content-guard.yml` runs on every PR.
```

**Verified for this plan**: `content-guard.yml` runs several things
`verify:ci` does not, and `verify:ci`'s command list is about to gain
`check:search-budget` (item 3 above). Comparing the two directly (both read
from the live files, current as of the SHAs above):

| Check | In `verify:ci`? | In `content-guard.yml`? |
|---|---|---|
| `npm ls --omit=dev` (dependency-graph/peer validity) | No | Yes (line 48) |
| Link checker | No | Yes (line 84, step "🔗 Link Checker") |
| `npm run test:audit` (Vitest, no coverage) | Yes | No — CI runs `npm run test:coverage` instead (line 148), a different, stricter command with coverage thresholds |
| Worker suite (`npm run test:coverage` inside the Worker package, workerd runtime) | No | Yes (line 162) |
| Playwright | `CI=1 npm run test:e2e` (generic) | `npx playwright test --project=mobile-375 --project=desktop-1280` (explicit projects, line 179) |
| `check:search-budget` | Will be Yes, after this step's item 3 fix | Will be Yes, after this step's item 3 fix |

Fix both claims in one edit pass (do this after item 3's `verify:ci` change,
so the corrected description reflects the final command list):

1. `CONTRIBUTING.md:22`: change the comment from `# production build (runs
   validate:content first)` to `# production build (image derivatives +
   astro build; run` `` `npm run validate:content` `` `separately first if you
   want the full content-quality gate)`.
2. `CONTRIBUTING.md:29-33`: change the overstated claim to something
   honest and bounded, e.g.: `This approximates the CI PR checks in one
   local command (lint, content validation, build, dist sanity, unit tests,
   search budget, browser tests, contract sync). CI additionally runs a
   dependency-graph check, a link checker, a Worker test suite, and uses
   coverage-threshold unit tests and explicit-viewport Playwright projects
   not reproduced here — see \`.github/workflows/content-guard.yml\` for the
   authoritative CI step list.` Do not attempt to make `verify:ci` actually
   run everything CI runs (adding the dependency-graph check, link checker,
   and Worker suite to a single local command is new scope, not a doc fix)
   — correct the claim to match reality, don't expand reality to match the
   claim.

### Frontend items verified current — no fix needed

Four of the six categories the master plan names ("Node 24, schema-path,
image-mode, build-command, CI parity, and removed legacy-fallback
statements") were checked against the live frontend active-docs set
(`README.md`, `AGENTS.md`, `CLAUDE.md`, `CONTRIBUTING.md`,
`docs/ARCHITECTURE.md`, `docs/SOURCE_OF_TRUTH.md`, `docs/tagging.md`,
`docs/webhook-integration.md`, `docs/report-pipeline-setup.md`,
`docs/supported-dependency-matrix.md`, `docs/DEPLOYMENT_SECURITY_HEADERS.md`,
`docs/EDITORIAL.md`, `docs/EDITORIAL_VOICE.md` — the exact list
`scripts/check-doc-drift.js:45-58` checks) and found **already current, no
change required**:

- **Node 24**: `.nvmrc` = `24`, `package.json` engines = `>=24.0.0 <25`,
  every `.github/workflows/*.yml` uses `node-version: 24` (14 occurrences,
  all consistent), and `CONTRIBUTING.md:5` / `docs/supported-dependency-matrix.md:11`
  both correctly state Node 24.x. (`grep -n "Node\b" <active docs>` and
  `grep -rn "node-version" .github/workflows/*.yml`.)
- **schema-path**: zero occurrences of the stale `src/content/config.ts`
  path in any active doc (`grep -n "src/content/config\.ts" <active docs>`
  returns nothing) — and the existing `stale_schema_path` invariant check
  already guards against regression.
- **image-mode**: no stale image-delivery-mode claims found (`grep -in
  "IMAGE_DELIVERY_MODE\|image.delivery.mode\|delivery mode" <active docs>`
  returns nothing beyond one accurate `CONTRIBUTING.md` mention of optional
  R2 credentials).
- **legacy-fallback**: no "legacy fallback" language found in any active doc
  (`grep -in "legacy fallback" <active docs>` returns nothing).

**Do not search further for these four** — an open-ended repo-wide grep will
also match `plans/060/spec.md` (the master plan document, which legitimately
describes historical/target-state findings as of its own baseline SHA — see
Scope) and produce a false positive. The acceptance criterion for these four
categories is "verified current as of this phase's dispatch," not "found and
fixed" — record in your final report that they were checked and are clean,
with the commands above, and do not invent a change to satisfy the master
plan's bullet list. Only the two real findings — build-command and CI-parity
(item 6) — need an edit.

## Commands you will need

| Purpose | Command | Repo | Provenance | Expected on success |
|---|---|---|---|---|
| Backend doc-drift | `make docs-check` | backend | declared | exit 0 |
| Backend unit tests (doc-drift module) | `pytest tests/unit/docs/test_check_doc_drift.py -v` | backend | declared | all pass, including your two new tests |
| Backend plans ledger check | `make plans-ledger-check` | backend | declared | exit 0 |
| Backend quality workflow syntax check | `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/quality.yml'))"` | backend | declared | no exception |
| Fetch gitleaks checksum (read-only, for step verification only) | `curl -sSL https://github.com/gitleaks/gitleaks/releases/download/v8.18.1/gitleaks_8.18.1_checksums.txt \| grep linux_x64` | backend | executed | prints the line quoted above |
| Frontend lint | `npm run lint` | frontend | declared | exit 0 |
| Frontend doc-drift | `npm run check:doc-drift` | frontend | declared | exit 0 |
| Frontend unit tests (new + existing) | `npx vitest run tests/check-search-budget.test.ts tests/contract-sync.test.ts` | frontend | declared | all pass |
| Frontend contract-sync strict (live) | `BACKEND_SCHEMA_PATH=<absolute path> npm run check:contract-sync` | frontend | declared | exit 0 |
| Frontend contract-sync strict (snapshot) | `node scripts/check-contract-sync.js --strict --snapshot .contract-snapshots/frontend_schema.snapshot.json src/content.config.ts` | frontend | executed | exit 0 |
| Frontend build + search budget (end to end) | `npm run build && npm run check:search-budget` | frontend | declared | exit 0 |
| Frontend full local gate | `npm run verify:ci` | frontend | declared | exit 0 (slow — lint, validate:content, build, test:dist, search-budget, test:audit, e2e, contract-sync) |

**Path resolution reminder** (same issue as Phase 0): `BACKEND_SCHEMA_PATH`'s
default in `check-contract-sync.js` is relative to the frontend checkout and
does not resolve inside an isolated worktree — export an absolute path to a
real backend checkout before running any command that needs it, or STOP and
report if you don't have one.

## Scope

**In scope — backend (`noticiencias_news_collector/`):**
- `.github/workflows/quality.yml` (Gitleaks step only)
- `docs/PIPELINE_CONTRACTS.md` (the one section quoted above)
- `docs/ARCHITECTURE.md` (the one line quoted above)
- `scripts/check_doc_drift.py` (`check_invariants()` only — add the new
  checks, do not restructure the function)
- `tests/fixtures/doc-drift/stale/README.md` (add one line)
- `tests/unit/docs/test_check_doc_drift.py` (add one test function)
- `plans/060/todo.md` (check off the five Phase-1 boxes under "Wave A")
- `plans/060/phase-1-trust-gates/todo.md` (this phase's own checklist)

**In scope — frontend (`noticiencias/`):**
- `package.json` (`scripts` block: `check:search-budget` new entry,
  `check:contract-sync` gets `--strict`, `verify:ci` gets
  `check:search-budget` inserted)
- `.github/workflows/content-guard.yml` (new "📏 Search Budget" step; the
  `--strict` addition to the snapshot-mode invocation)
- `.github/workflows/sync-contract-snapshot.yml` (read to confirm no
  non-strict `check-contract-sync.js` invocation needs fixing — likely no
  edit needed, see item 4)
- `tests/check-search-budget.test.ts` (new)
- `src/pages/admin/dashboard.astro` (lines 106 and 118 only)
- `CONTRIBUTING.md` (the two spans quoted above, item 6)

**Out of scope (do NOT touch, even though they look related):**
- **`plans/060/spec.md`** (the master plan document, in the backend repo) —
  it describes the *findings as of its own baseline SHA* (`d63cbea`),
  including the same stale five-step publication-date list you're fixing in
  `docs/PIPELINE_CONTRACTS.md`. That's a historical planning artifact, not an
  active doc — the doc-drift checker does not scan `plans/`, and this phase
  does not either. Leave it exactly as written.
- `docs/adr/0005-*.md` and `docs/adr/0007-*.md` (frontend) — pre-existing
  uncommitted changes from Phase 0's cleanup, unrelated to this phase; leave
  them as-is (see the preamble note above).
- Any change to `scripts/check-search-budget.js`'s own logic — it is
  complete and correct as written; this phase only wires it up and tests it.
- Any change to `scripts/check-contract-sync.js`'s own logic — only the
  callers (package.json, workflow YAML) change.
- Any change to `src/components/ds/organisms/DashboardHealthList.astro` —
  it already correctly supports `'unknown'` as a status; only the caller
  (`dashboard.astro`) needs fixing.
- Adding a real hero-image or lint metric to `scripts/generate-metrics.js` —
  out of scope; `'unknown'` is the correct fix per the master plan's
  acceptance criterion.
- Making `verify:ci` cover everything `content-guard.yml` covers (dependency
  graph, link checker, worker suite) — out of scope; the fix is correcting
  the doc claim, not expanding the command.
- Any file under `plans/048/` or `plans/060/phase-0-baseline/` — unrelated
  or already-completed work; do not touch.

## Git workflow

- Backend branch: `architecture/060-01-trust-gates`.
- Frontend branch: `architecture/060-01-trust-gates` (independent branch,
  same name, separate repo).
- Backend: two commits — (1) Gitleaks checksum verification, (2) the doc
  fix + invariant + fixture test **together, in one commit** (see "Sequencing
  matters" above; do not split this into "fix docs" then "add check" commits,
  the intermediate state fails `test_live_repo_docs_pass`).
- Frontend: recommend three commits — (1) search-budget wiring +
  `verify:ci` update + tests, (2) contract-sync `--strict`, (3) dashboard
  fix + `CONTRIBUTING.md` fix (these two are small and related to the same
  "stop overstating what's verified" theme, but touch unrelated files —
  either one commit or two is fine, your judgment).
- Conventional-commit style matching each repo's `git log`.
- Do NOT push or open a PR — leave commits in the worktree for the reviewer.

## Steps

### Step 0: Establish a green baseline

Backend: `make docs-check`, `make plans-ledger-check`,
`pytest tests/unit/docs/test_check_doc_drift.py -v`.

Frontend: `npm run lint`, `npm run check:doc-drift`, and (with
`BACKEND_SCHEMA_PATH` exported as an absolute path)
`node scripts/check-contract-sync.js --strict --snapshot .contract-snapshots/frontend_schema.snapshot.json src/content.config.ts`.

If a `declared` command fails on the unmodified checkout: STOP and report —
do not fix a pre-existing failure as part of this phase.

**Verify**: all listed commands exit 0 (green baseline) before any edit.

### Step 1 (backend): Gitleaks checksum verification

Replace `.github/workflows/quality.yml:44-48`'s "Install Gitleaks" step.
Target shape (adapt to the workflow's existing YAML style/indentation —
match surrounding steps, don't introduce a different quoting convention):

```yaml
      - name: Install Gitleaks
        run: |
          set -euo pipefail
          GITLEAKS_VERSION="8.18.1"
          WORKDIR="$(mktemp -d)"
          curl -sSL -o "$WORKDIR/gitleaks.tar.gz" \
            "https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}/gitleaks_${GITLEAKS_VERSION}_linux_x64.tar.gz"
          curl -sSL -o "$WORKDIR/checksums.txt" \
            "https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}/gitleaks_${GITLEAKS_VERSION}_checksums.txt"
          grep "gitleaks_${GITLEAKS_VERSION}_linux_x64.tar.gz" "$WORKDIR/checksums.txt" > "$WORKDIR/expected.sha256"
          (cd "$WORKDIR" && sha256sum -c expected.sha256)
          mkdir -p "$RUNNER_TEMP/bin"
          tar -xz -C "$RUNNER_TEMP/bin" -f "$WORKDIR/gitleaks.tar.gz" gitleaks
          echo "$RUNNER_TEMP/bin" >> "$GITHUB_PATH"
```

Key properties this must preserve: `set -euo pipefail` (a failed download or
failed checksum check must fail the step, not silently continue); download
to a temp dir and verify **before** extracting (no pipe-to-tar); install to
`$RUNNER_TEMP/bin` + `$GITHUB_PATH` rather than `/usr/local/bin` (job-local,
least-privilege — matches the master plan's "install in a job-local path and
keep least-privilege permissions"); the `grep` step must produce a
`sha256sum -c`-compatible single line (verified above: the checksums file's
format already matches — two spaces, filename exactly as downloaded).

**Verify**: `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/quality.yml'))"`
exits 0 (valid YAML). This step cannot be fully exercised locally (no GitHub
Actions runner available in the worktree) — write the **checksum-tampering
fixture test** instead, as a standalone script proving the verification
logic itself is correct:

Create `scripts/verify_gitleaks_checksum_test.sh` (a small, self-contained,
throwaway-safe shell script — not wired into any CI job, just proof the
sha256sum-based verification catches tampering):

```bash
#!/usr/bin/env bash
set -euo pipefail
WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT
echo "not the real binary" > "$WORKDIR/gitleaks.tar.gz"
echo "0000000000000000000000000000000000000000000000000000000000000000  gitleaks.tar.gz" > "$WORKDIR/expected.sha256"
if (cd "$WORKDIR" && sha256sum -c expected.sha256) 2>/dev/null; then
  echo "FAIL: checksum verification did not catch a tampered/corrupted file"
  exit 1
fi
echo "PASS: sha256sum -c correctly rejects a mismatched file (exit $?)"
```

Run it (`bash scripts/verify_gitleaks_checksum_test.sh`) and confirm it
prints `PASS` and exits 0 (the script's own exit 0 means "the tamper
detection worked," not "the tampered file passed" — read the script's logic
carefully, the assertion is inverted-on-purpose: it fails *itself* if
`sha256sum -c` does NOT reject the bad file).

**Verify**: `bash scripts/verify_gitleaks_checksum_test.sh` exits 0 and
prints `PASS`.

### Step 2 (backend): Fix stale publication-date docs, extend the doc-drift invariant, add the fixture test — one commit

Apply, in this order, within a single commit:

1. Replace the quoted span in `docs/PIPELINE_CONTRACTS.md:63-79` with the
   exact replacement text given above.
2. Replace the quoted line in `docs/ARCHITECTURE.md:151` with the exact
   replacement text given above.
3. Add the two new `if` blocks to `check_invariants()` in
   `scripts/check_doc_drift.py`, exactly as specified above.
4. Add one line containing the literal phrase `current date as last resort`
   to `tests/fixtures/doc-drift/stale/README.md` (read the file first — it
   already has 2-3 lines for other stale-claim tests; append, don't replace).
5. Add `test_flags_stale_publication_date_fallback` to
   `tests/unit/docs/test_check_doc_drift.py`, modeled on
   `test_flags_stale_schema_path`.

**Verify**: `pytest tests/unit/docs/test_check_doc_drift.py -v` — all tests
pass, including your new one and (critically) `test_live_repo_docs_pass`
(this is the test that would have failed had you sequenced the docs fix and
the invariant addition into separate commits). `make docs-check` exits 0.
`grep -rn "current date as last resort\|current date when source dates are missing" docs/PIPELINE_CONTRACTS.md docs/ARCHITECTURE.md`
returns nothing (confirms both stale phrases are gone from the two active
docs — do not run this grep repo-wide, it will match `plans/060/spec.md`,
which is correctly out of scope).

### Step 3 (frontend): Wire `check:search-budget`

1. Add the `package.json` script entry, add the CI step in
   `content-guard.yml`, add it to `verify:ci` — exactly as specified in
   "Frontend item 3" above.
2. Write `tests/check-search-budget.test.ts` with the two cases described
   above, taking care to trip the gzip ceiling specifically (not the bloat
   heuristic) in the oversized case.

**Verify**: `npx vitest run tests/check-search-budget.test.ts` — both cases
pass. `npm run build && npm run check:search-budget` — exits 0 against the
real current build output (confirms the wiring works end-to-end, not just
in the unit test).

### Step 4 (frontend): Make `check:contract-sync` strict everywhere

Apply the three changes in "Frontend item 4" above (package.json, the
snapshot-mode CI invocation, and the read-only check of
`sync-contract-snapshot.yml`).

**Verify**: with `BACKEND_SCHEMA_PATH` exported as an absolute path,
`npm run check:contract-sync` exits 0; and
`node scripts/check-contract-sync.js --strict --snapshot .contract-snapshots/frontend_schema.snapshot.json src/content.config.ts`
exits 0.

### Step 5 (frontend): Dashboard hard-coded states + `CONTRIBUTING.md` claims

1. Change `src/pages/admin/dashboard.astro:106` and `:118` from `'pass' as
   const` to `'unknown' as const`, updating each `detail` string as
   specified in "Frontend item 5" above.
2. Apply the two `CONTRIBUTING.md` fixes from "Frontend item 6" above, after
   Step 3's `verify:ci` change has already landed (so the corrected claim
   reflects the final command list, including `check:search-budget`).

**Verify**: `npm run lint` exits 0 (confirms no TypeScript/Astro type error
from the status-literal change — `'unknown'` is already a valid member of
`DashboardHealthList.astro`'s `status` union type per its existing prop
signature, `line 5`: `status: 'pass' | 'fail' | 'warning' | 'unknown'`).
Manually re-read the two edited `CONTRIBUTING.md` spans to confirm they no
longer overstate what the commands do.

### Step 6: Close out

- Check off the five Phase-1 checkboxes under "Wave A → Phase 1" in
  `plans/060/todo.md` (backend) — re-read the current text first in case
  drift occurred.
- Check off this phase's own `plans/060/phase-1-trust-gates/todo.md`.
- Do not touch any other wave's checkboxes; do not mark plan 060 DONE
  anywhere.

**Verify**: `git diff --stat` in each repo shows only the in-scope files
listed above.

## Test plan

- Backend: `pytest tests/unit/docs/test_check_doc_drift.py -v` (existing
  suite + your new `test_flags_stale_publication_date_fallback`) must fully
  pass, including `test_live_repo_docs_pass`. No other backend test file is
  affected by this phase's changes (the Gitleaks step change is CI-only YAML
  with no corresponding unit test — the tamper-detection shell script in
  Step 1 is the closest available proof).
- Frontend: `tests/check-search-budget.test.ts` (new, 2 cases) plus a
  re-run of the existing `tests/contract-sync.test.ts` (unaffected by this
  phase, but run it to confirm the `--strict` package.json change doesn't
  break anything that shells out to `check:contract-sync` indirectly).
- Full verification: `npm run verify:ci` (frontend, slow) and `make
  docs-check && make plans-ledger-check` (backend) both green at the end.

## Done criteria

Machine-checkable. ALL must hold:

- `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/quality.yml'))"` (backend) exits 0
- `bash scripts/verify_gitleaks_checksum_test.sh` (backend) exits 0, prints `PASS`
- `pytest tests/unit/docs/test_check_doc_drift.py -v` (backend) — all pass
- `grep -rn "current date as last resort\|current date when source dates are missing" docs/PIPELINE_CONTRACTS.md docs/ARCHITECTURE.md` (backend) returns nothing
- `npx vitest run tests/check-search-budget.test.ts` (frontend) — both cases pass
- `npm run build && npm run check:search-budget` (frontend) exits 0
- `BACKEND_SCHEMA_PATH=<absolute path> npm run check:contract-sync` (frontend) exits 0
- `node scripts/check-contract-sync.js --strict --snapshot .contract-snapshots/frontend_schema.snapshot.json src/content.config.ts` (frontend) exits 0
- `npm run lint` (frontend) exits 0
- `git diff --stat` in each repo lists only the in-scope files from "Scope"
- `plans/060/todo.md` Phase-1 checkboxes and
  `plans/060/phase-1-trust-gates/todo.md` are checked off

## STOP conditions

Stop and report back (do not improvise) if:

- Any "Current state" excerpt doesn't match the live file (drift since this
  plan was written).
- `gh release view v8.18.1 --repo gitleaks/gitleaks` or the checksums-file
  download fails or the asset names differ from what's quoted above (the
  release could theoretically change, though unlikely for a tagged release)
  — re-verify rather than proceeding on stale assumptions.
- The re-run strict editorial or contract-sync checks fail where this plan
  says they currently pass — that means backend or frontend schema content
  changed since this plan's baseline SHAs; report the new output, don't
  paper over it.
- `test_live_repo_docs_pass` fails after Step 2 — re-check that both doc
  replacements were applied exactly and that no other active doc contains
  either stale phrase.
- You find a genuine stale instance of the four "verified current" doc
  categories (Node/schema-path/image-mode/legacy-fallback) that this plan's
  recon missed — report it rather than fixing it silently; it means the
  live repo has drifted from this plan's evidence, which should be
  reconciled explicitly, not patched over inside this phase's diff.

## Maintenance notes

- The new `stale_publication_date_fallback` invariant in
  `check_doc_drift.py` is a permanent regression guard — any future doc edit
  that reintroduces either stale phrase will fail `make docs-check`. Whoever
  next edits `docs/PIPELINE_CONTRACTS.md`'s identity-order section should
  know this check exists.
- `verify:ci`'s command list now includes `check:search-budget` — any future
  addition to `content-guard.yml`'s build-and-test job should keep
  `verify:ci` and the CI step list in sync, or `CONTRIBUTING.md`'s corrected
  claim (item 6) drifts stale again, the same way it did before this phase.
- The dashboard's two `'unknown'` states (hero images, linting) are a
  placeholder, not a resolution — a future phase or plan that wires a real
  hero-image or lint-status metric into `pipeline-metrics.json` should flip
  these back to a measured `pass`/`fail`/`warning`, not leave them
  permanently `unknown`.
