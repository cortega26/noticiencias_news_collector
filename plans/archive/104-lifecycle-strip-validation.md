# Plan 104: Strip lifecycle metadata before publish contract validation

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat e77a039..HEAD -- news_collector/contracts/adapters.py news_collector/contracts/collector.py news_collector/contracts/common.py apps/refinery/main.py news_collector/logic/workflows/refinery_engine.py news_collector/storage/article_repository.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `e77a039`, 2026-09-16

## Why this matters

Article 502 was audited on 2026-09-03 (state `passed`) and became
permanently un-republishable: `update_article_audit_status` persists
`article_metadata["audit"]`, and the publish S1 guard re-validates the
DB-sourced payload with `CollectorArticleModel`, whose metadata model is
`extra="forbid"` with no `audit` field → `contract_validation` fails with
"Extra inputs are not permitted". Audit-then-republish is deterministically
broken for every audited article (same latent trap for the `publication` key).
Operator decision (recorded): strip run-scoped keys at validation, do NOT
permit them in the collector contract (wrong layer — lifecycle state is not
collector content).

## Current state

The relevant files, each with one line on its role:

- `news_collector/contracts/common.py` — `ArticleMetadataModel`, `extra="forbid"`, no `audit`/`publication` (lines 29-44)
- `news_collector/contracts/collector.py` — `CollectorArticleModel`, `extra="forbid"` (lines 130, 158, 166)
- `news_collector/storage/article_repository.py` — writes `audit` (lines 494-512); `reset_article_for_reprocess` pops `audit` + `publication` as run-scoped (1459-1460)
- `apps/refinery/main.py` — `validate_collector_payload` = bare `model_validate(...).model_dump()` (536-537), injected at 545
- `news_collector/logic/workflows/refinery_engine.py` — S1 guard calls the validator on the DB-sourced dict (346-368); `_normalize_article_payload` runs AFTER (370)

Excerpts (all read directly):

`common.py:29-44`:

```python
class ArticleMetadataModel(BaseModel):
    """Validated metadata attached to collected articles."""
    source_metadata: Dict[str, Any] = Field(default_factory=dict)
    credibility_score: float | None = None
    ... (enrichment, image_*, normalized_*, original_url)
    model_config = ConfigDict(extra="forbid")
```

`article_repository.py:494-512` — the writer:

```python
article_metadata = dict(article.article_metadata or {})
audit_meta = dict(article_metadata.get("audit") or {})
audit_meta.update({"state": ..., "reason": ..., "updated_at": ..., ...})
article_metadata["audit"] = audit_meta
article.article_metadata = article_metadata
```

`article_repository.py:1459-1460` — the precedent (run-scoped keys):

```python
metadata.pop("audit", None)
metadata.pop("publication", None)
```

`apps/refinery/main.py:536-537`:

```python
def validate_collector_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    return CollectorArticleModel.model_validate(payload).model_dump()
```

The 502 failure signature (from `data/runtime/publication_attempts/502.json`):
`1 validation error for CollectorArticleModel / article_metadata.audit /
Extra inputs are not permitted [type=extra_forbidden,
input_value={'state': 'passed', 'reas…'}]`.

Repo conventions that apply here:

- LAW-B2: shape conversion lives in `contracts/adapters.py` — the strip helper goes there, not in `main.py` or the engine.
- LAW-B1: boundary stays typed — the validator still returns a validated `CollectorArticleModel` dump; we only narrow its INPUT to content keys.
- The persisted DB row must remain byte-identical (audit history is evidence).

## Commands you will need

| Purpose   | Command                  | Provenance | Expected on success |
|-----------|--------------------------|------------|---------------------|
| Install   | `make bootstrap`         | declared   | exit 0 |
| Lint      | `make lint`              | declared   | exit 0 |
| Type      | `make type`              | declared   | exit 0, ratchet passes |
| Tests     | `make test`              | declared   | all pass |
| Contracts | `make test-contracts`    | declared   | all pass |
| Boundaries| `make test-boundaries`   | declared   | all pass |

## Scope

**In scope** (the only files you should modify):

- `news_collector/contracts/adapters.py` (new strip helper)
- `apps/refinery/main.py` (`validate_collector_payload` only — call the helper)
- `tests/unit/contracts/test_collector_contract.py` (or the closest existing contract-test file — check first) + `tests/decompose_refinery/` if a publish-path test fits there

**Out of scope** (do NOT touch, even though they look related):

- `ArticleMetadataModel` / `CollectorArticleModel` schemas — no new fields, operator decided.
- `update_article_audit_status`, `reset_article_for_reprocess`, storage writes — persistence behavior unchanged.
- `mark_article_published` / `publication` metadata production — unchanged.
- Serving-side validation paths — check whether they share `validate_collector_payload`; if they do, they get the fix consistently (fine), but do not otherwise alter serving.

## Git workflow

- Branch: `advisor/104-lifecycle-strip-validation`
- Conventional commits, e.g. `fix(contracts): strip lifecycle metadata before publish validation`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 0: Establish a green baseline

Run `Install`, then `Lint`, `Type`, `Tests` on the unmodified checkout. On any
`declared`-command failure on the clean tree (modulo the known flaky
`test_429_retry_after_handling`, which passes in isolation): **STOP and report**
with exact output. Reproduce the bug first: build the dict from article 502's
persisted shape (metadata WITH `audit: {state passed, …}`) and run it through
`validate_collector_payload` — record the `extra_forbidden` failure.

**Verify**: reproduction shows the `article_metadata.audit` rejection on the unmodified checkout.

### Step 1: Confirm the full lifecycle-key set

1. Grep all writers of top-level `article_metadata` keys outside the contract fields: `rg -n "article_metadata\[[\"'][a-z_]+[\"']\] *=" news_collector/ apps/ | grep -v test`. List every key ever persisted that `ArticleMetadataModel` forbids.
2. Confirm `publication` is one of them (engine comment at `refinery_engine.py:90-95` references `article_metadata["publication"]["refinery_id"]` — verify the writer).
3. The strip set = confirmed lifecycle keys (expect at minimum `audit` + `publication`). If a third key appears that is CONTENT (not run-scoped), STOP and report — the strip list needs a design decision, not a guess.

**Verify**: written key inventory with writer file:line for each.

### Step 2: Add the adapter helper + wire the validator

1. In `news_collector/contracts/adapters.py`, add (read the file's existing helper style first and match it):

```python
LIFECYCLE_METADATA_KEYS = frozenset({"audit", "publication"})

def strip_lifecycle_metadata(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Return a copy of a DB-sourced article payload without run-scoped
    lifecycle keys (audit/publication state), which are persisted evidence
    but not part of any collector content contract. Never mutates input."""
```

   Must deep-copy the metadata mapping (no aliasing the caller's dict), must preserve ALL other keys byte-identically.
2. In `apps/refinery/main.py::validate_collector_payload`, apply the helper to a copy before `model_validate`. Keep the return shape identical.
3. Check other `validate_collector_payload`-equivalent call sites (serving publish path? `grep -rn "model_validate(payload)"`): if the serving path validates DB-sourced payloads the same way, route it through the helper too ONLY if it is the same one-line change — otherwise report it, don't expand.

**Verify**: Step-0 reproduction now validates cleanly; `make lint` → exit 0.

### Step 3: Add regression tests

1. Contract test with 502's exact shape: metadata containing `audit: {state: "passed", reason: "", updated_at: ...}` (and a `publication`-keyed variant) → `validate_collector_payload` (or the helper + model) passes; assert the INPUT dict is unmutated (audit key still present afterwards) while the OUTPUT has no lifecycle keys.
2. Negative guard: genuinely unknown junk key (e.g. `article_metadata: {bogus_key: 1}`) STILL fails `extra_forbidden` (the strip is a scalpel, not a blanket `extra=ignore`).

**Verify**: new tests pass; `make test-contracts` green.

### Step 4: Run the full gates

**Verify**: `make lint && make type && make test && make test-contracts && make test-boundaries` → all exit 0 (modulo known flake only).

## Test plan

- New: 502-shape strip test (+publication variant), input-immutability assertion, junk-key-still-rejected guard.
- Existing contract + boundary + refinery suites green (no schema change, so no golden drift expected).

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `make lint`, `make type`, `make test`, `make test-contracts`, `make test-boundaries` all exit 0
- [ ] 502's persisted metadata shape validates post-fix (pinned by test); DB row untouched (immutability test)
- [ ] Unknown junk metadata keys still rejected (no blanket loosening — grep confirms `extra="forbid"` unchanged in both models)
- [ ] `git diff --name-only e77a039...HEAD` lists only the in-scope files (plus already-merged wave files, expected)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- The code at the locations in "Current state" doesn't match the excerpts.
- Step-0 reproduction does NOT show the `audit` rejection (payload assembly differs from the analysis — report actuals).
- Step 1 finds a content key (not run-scoped) that also needs stripping.
- The serving publish path needs more than the same one-line change.
- A step's verification fails twice after a reasonable fix attempt.

## Maintenance notes

- If new lifecycle keys are ever persisted to `article_metadata`, they must be added to `LIFECYCLE_METADATA_KEYS` with a comment naming the writer — otherwise re-publish breaks again the same way. Consider asserting this invariant in the contract test (round-trip all known writers).
- Reviewers: the load-bearing property is input-immutability (audit history must survive validation).
- **Deferred:** moving audit/publication state out of `article_metadata` into durable lifecycle tables (plan 060 Phase 3 direction) — the architectural fix; this plan is the minimal unblock.
