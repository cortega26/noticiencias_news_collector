# Plan 142: Close four small security exposures (artifact, tokens, path, payload)

> **Executor instructions**: Follow this plan step by step. Run every verification
> command and confirm the expected result before moving to the next step. If
> anything in the "STOP conditions" section occurs, stop and report — do not
> improvise. When done, update the status row for this plan in `plans/README.md`.
>
> **Drift check (run first)**:
> `git diff --stat 1ff6926..HEAD -- .github/workflows/quality.yml .github/workflows/source_reliability.yml .github/workflows/system-verification.yml .github/workflows/mutation.yml news_collector/logic/workflows/image_handler.py news_collector/contracts/webhook.py news_collector/serving/api.py tests/`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S-M
- **Risk**: LOW
- **Depends on**: none, but **sequence against plans 138, 139, 143, 144, 145** for
  the shared CI files
- **Category**: security
- **Planned at**: commit `1ff6926`, 2026-10-18

## Why this matters

Four independent, small exposures. **This repository is public**
(`gh repo view --json visibility` → `PUBLIC`), which raises the stakes on the
first item.

1. **Unredacted secret-scan report is uploaded as a CI artifact.**
   `.github/workflows/quality.yml:65-83` runs gitleaks without `--redact`
   (deliberately, so the baseline still matches) and then uploads the whole
   `reports/security` directory. The report schema carries the matched value in
   clear text (confirmed against the committed `.gitleaks-baseline.json`, which
   stores a `Secret` field). On a public repo, artifacts are downloadable by
   anyone with repository read access — so any secret a future PR introduces gets
   republished for the artifact retention window, undoing the "delete the value"
   remediation and lengthening the rotation obligation.
2. **Three workflows that execute PR code declare no `permissions:`**
   (`source_reliability.yml`, `system-verification.yml`, `mutation.yml`), unlike
   the other 18. Without an explicit block they inherit the repository default
   token scope.
3. **The image-asset write path has no slug/containment guard**, while both
   sibling writers do (`target_repo_writer.py:73-82` "NC-BE-015 S0 GUARD",
   `image_briefs.py:107-117` "NC-BE-087 S1 GUARD"). `image_handler.py:231-233`
   builds `assets_dir / f"{slug}{ext}"` and writes it; the slug can come back
   verbatim from the DB branch of the identity resolver
   (`publication_identity.py:251-260` → `_derive_slug` prefers `preferred_slug`),
   which only checks for a `YYYY-MM-DD-` prefix.
4. **The inbound webhook contract has uncapped collections**:
   `contracts/webhook.py:47-57` `errors: List[Any]` and an uncapped
   `diagnostics` list, plus an untyped `Dict[str, Any]` body on the route; the
   payload is persisted verbatim into an append-only JSON column. A caller
   holding the shared key can grow the SQLite DB without bound.

None of these is an active exploit; all four are cheap to close and the fix risk
is low.

## Current state

- `quality.yml:65-83` — the secret-scan step (report path
  `reports/security/gitleaks.json`, `--no-banner`, no `--redact`) followed by
  `actions/upload-artifact` with `path: reports/security`.
- `source_reliability.yml`, `system-verification.yml`, `mutation.yml` — no
  `permissions:` key at workflow or job level (verified: 0 matches each).
  Reference pattern: `quality.yml:16-18` and `ci.yml:15` (`contents: read`).
- `news_collector/logic/workflows/image_handler.py:231-233`:

```python
            filename = f"{slug}{ext}"
            local_path = assets_dir / filename
            local_path.write_bytes(response.content)
```

- `news_collector/logic/workflows/image_briefs.py:34-42` — `_validate_slug`
  (regex allowlist + `ValueError` naming the slug);
  `:107-117` — the resolved-path containment check to mirror.
- `news_collector/contracts/webhook.py:47-57` — `DiagnosticResult` with
  `errors: List[Any]`, while the module already caps other collections
  (`_MAX_PUBLICATION_IDS = 200`, `_MAX_PUBLICATION_ATTEMPT_REFS = 200`,
  `_MAX_DELIVERY_ID_LENGTH = 128` at `:16-19`) — follow that convention.
- `news_collector/serving/api.py:1318-1353` — the webhook route accepting the
  untyped body.

## Commands you will need

| Purpose            | Command                                                     | Provenance | Expected on success          |
|--------------------|-------------------------------------------------------------|------------|------------------------------|
| Install/baseline   | `make bootstrap`                                            | declared   | exit 0                       |
| Lint               | `make lint`                                                 | declared   | exit 0                       |
| Types + coverage   | `make type`                                                 | declared   | exit 0                       |
| Unit suite         | `make test`                                                 | declared   | all pass                     |
| Contracts          | `make test-contracts`                                       | declared   | exit 0                       |
| Focused tests      | `.venv/bin/pytest tests/test_webhook.py tests/unit -q --no-cov -k "image or webhook"` | declared | all pass   |
| Ledger             | `make plans-ledger-check`                                   | declared   | `validate_plans_ledger: OK`  |

Provenance: all `declared`.

## Scope

**In scope**:

- `.github/workflows/quality.yml` (sanitise before upload)
- `.github/workflows/{source_reliability,system-verification,mutation}.yml` (add `permissions`)
- `news_collector/logic/workflows/image_handler.py` (guard)
- `news_collector/contracts/webhook.py` (caps)
- `news_collector/serving/api.py` (body-size limit on the webhook route only)
- `tests/` — focused tests for 3 and 4; a workflow-lint-style check for 1-2 if one exists
- `docs/ci.md` — describe the sanitised artifact

**Out of scope** (do NOT touch):

- `.gitleaks.toml` / `.gitleaks-baseline.json` / `scripts/security_gate.py`
  (the gate's behaviour is correct; only the artifact changes).
- `publication_identity.py` — its DB branch semantics are deliberate (LAW-B5);
  the guard belongs on the writer.
- Any other route's body handling on the serving API.

## Git workflow

- Branch: `advisor/142-security-hygiene`
- Conventional commits, one per item, e.g.
  `fix(security): redact secret-scan artifacts before upload (plan 142)`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 0: Establish a green baseline

Run `make bootstrap`, `make lint`, `make type`, `make test`,
`make test-contracts`. Red baseline → STOP and report.

**Verify**: every command matches its expected result.

### Step 1: Sanitise the secret-scan artifact (do this first — it is the public-repo one)

1. Keep the gate reading the raw report. Then, before the upload step, write a
   sanitised copy for the artifact: strip or hash the fields that carry matched
   values (gitleaks JSON entries carry `Secret` and `Match`; the committed
   baseline confirms the shape) while keeping rule id, file, line, commit,
   author, date, and description. Preserve the raw file for the gate step only.
2. Upload only the sanitised directory (or replace `reports/security/gitleaks.json`
   with the sanitised copy after the gate has run and before the upload step —
   whichever is simpler and provably safe).
3. Add a tiny check so this cannot regress: a unit test in `tests/` that runs the
   sanitiser over a fixture report containing a sentinel fake value and asserts
   the sentinel is absent from the output while the rule id remains. **Never use
   a real secret in the fixture.**
4. Update `docs/ci.md` to say the uploaded report is sanitised.

**Verify**: `.venv/bin/pytest tests/ -q --no-cov -k "gitleaks or sanit"` → pass;
`grep -n "upload-artifact\|sanit" .github/workflows/quality.yml` → the sanitised path is what gets uploaded.

### Step 2: Declare read-only tokens

5. Add at the top of each of the three workflows (job level is fine if the
   workflow has several jobs with different needs — read the files first):

```yaml
permissions:
  contents: read
```

6. Confirm no step in those workflows needs a wider scope (grep for
   `gh `, `git push`, `issue`, `contents: write`); if one does, STOP and report
   rather than granting write.

**Verify**: `grep -c "permissions:" .github/workflows/{source_reliability,system-verification,mutation}.yml` → 1 each; YAML parses.

### Step 3: Guard the image-asset write

7. In `image_handler.py`, before building the filename:
   - validate the slug with an allowlist regex (mirror `image_briefs._validate_slug`
     — mirror the pattern; do not import a private helper across modules), and
   - verify the resolved path stays inside `assets_dir` (mirror the
     `resolve().relative_to(...)` containment check at `image_briefs.py:107-117`).
   On failure: log a warning with the slug and return the module's existing
   failure value (`None` here) — do not raise into the publication flow, and do
   not write anything.
8. If the enriched candidate has no usable slug, prefer the deterministic
   fallback already used by `_derive_slug` (`slugify_text(title, fallback=...)`)
   rather than aborting the image step.

**Verify**: `.venv/bin/pytest tests/ -q --no-cov -k "image"` → all pass, plus new
cases (below).

### Step 4: Cap the inbound payload

9. In `contracts/webhook.py`, cap every collection and free-form string that is
   persisted: `DiagnosticResult.errors` (item count and/or serialized size),
   the `diagnostics` list, and the free-form strings (`commit_sha`, `branch`,
   `frontend_ref`, `run_url`) — follow the module's existing `_MAX_*` constant
   convention and its validators. Bound them generously: reject only what no
   legitimate CI payload would contain (state the chosen numbers in the PR).
10. In `serving/api.py`, reject oversize request bodies on the webhook route
    before validation (e.g. a size check on the raw body with a documented cap,
    returning 413). Keep the route's existing "receipt-first, always 202 on
    success" semantics for accepted payloads.
11. Update `docs/PIPELINE_CONTRACTS.md` if it documents the envelope's fields
    (check `grep -n "webhook" docs/PIPELINE_CONTRACTS.md`; the doc must stay
    true — `make docs-check`).

**Verify**: `.venv/bin/pytest tests/test_webhook.py -q --no-cov` → all pass, plus
new cases (below).

## Test plan

- **Image guard** (`tests/unit/logic/workflows/` or beside the existing image
  tests — locate with `grep -rln "image_handler" tests/`): a traversal-shaped slug
  (`../evil`), an absolute path, and a slug with separators are all rejected and
  nothing is written; a normal slug still writes into `assets_dir`.
- **Webhook caps**: an over-limit `errors` list is rejected by validation; an
  oversize body is rejected at the route with 413; a normal payload is accepted
  and persisted (assert on the stored row).
- **Artifact sanitiser**: the sentinel test from Step 1.

**Verify**: `make test && make test-contracts` → green.

## Done criteria

All must hold:

- [ ] `make lint`, `make type`, `make test`, `make test-contracts` exit 0
- [ ] The uploaded artifact provably contains no matched secret values (sentinel test)
- [ ] Three workflows declare `permissions: contents: read`; YAML valid
- [ ] Image guard rejects traversal/absolute/separated slugs and writes nothing (tests)
- [ ] Webhook caps enforced with tests; docs updated; `make docs-check` exits 0
- [ ] `git diff --name-only main...HEAD` lists only in-scope files
- [ ] `plans/README.md` row 142 updated; `make plans-ledger-check` → OK

## STOP conditions

- A secret-scan fixture or an existing report contains what looks like a real
  credential → do **not** copy it anywhere; report the file:line and the
  credential type only, and continue with a synthetic sentinel.
- gitleaks' JSON shape in the installed version does not include `Secret`/`Match`
  fields → report the actual shape before writing the sanitiser.
- A workflow needs more than `contents: read` → stop and report (do not widen).
- Capping the envelope would reject a payload the frontend actually sends →
  report the payload shape from the frontend repo instead of loosening silently.

## Maintenance notes

- The sanitiser is a policy point: if gitleaks changes its report schema, the
  sanitiser must be updated in the same change as the version pin
  (`GITLEAKS_VERSION` in `quality.yml`).
- Reviewer should scrutinise: that no step uploads raw `reports/security`
  anymore, and that the body cap cannot reject the real CI payloads (compare the
  observed sizes).
- **Deferred:** per-caller webhook credentials (the key is shared with CI today).
  Unblocked by a decision about the hosted inbox's auth model (ADR-0011 area).
