# Plan 122: Restore the adapter choke point (manual-ingest payload, source_id stamping)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 04016ca..HEAD -- news_collector/logic/workflows/manual_ingest.py news_collector/logic/workflows/live_source_drift.py news_collector/contracts/adapters.py news_collector/serving/api.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: none (read backend plan 100's merged result first — it
  moved manual-ingest policy gates to config; this plan moves payload
  shape, a different concern in the same file — sequence, don't duplicate)
- **Category**: tech-debt
- **Planned at**: commit `04016ca`, 2026-10-11
- **Issue**: omit

## Why this matters

LAW-B2 names `contracts/adapters.py` the only shape-conversion choke
point, and explicitly rejects repeating `source_id`/publication-field
normalization outside adapter code — yet the manual-ingest workflow
hand-builds the `CollectorArticleModel` input dict inline (validated only
after the fact), and `source_id` stamping/projection is hand-rolled in
three modules. Every contract change must then be made in N places that
can drift (adapter says one shape, workflow builds another), and a
`source_id` canonicalization change (e.g. the `manual_` prefix rules)
won't reach drift reports or serving projections. Mechanical move, fully
contract-tested — but MED risk because mis-mapping silently changes stored
articles.

## Current state

Facts (all verified 2026-10-11):

```python
# manual_ingest.py:659-683 — hand-built collector payload in workflow code
payload = {
    "url": canonical_url,
    "original_url": canonical_url,
    "title": merged["title"],
    ...
    "source_id": source_id,
    "source_name": source_config.get("name") or source_id,
    "category": source_config.get("category") or "multidisciplinary",
    ...
}
return payload, None
# validated only afterwards at manual_ingest.py:416:
model = CollectorArticleModel.model_validate(payload)
```

The same file uses the sanctioned path on the return leg
(`manual_ingest.py:433,450` call `adapt_article_to_export`) — the
ingest leg is the breach, the export leg is the exemplar.

```python
# live_source_drift.py:36
{"source_id": source_id, **dict(raw)}
# manual_ingest.py:665,737 — "source_id": source_id / export_model.source_id
# manual_ingest.py:410,424,445 — per-attempt source_id echoes
# serving/api.py:396,473,1110 — row.source_id projections
```

Repo conventions: LAW-B2 (adapters own shape conversion; no business
rules in adapters); LAW-B1 (typed boundaries); contract/adapter changes
are High class → baseline + `make test-contracts`. Prior related: plan 100
moved manual-ingest *policy* (credibility/tier/word-gates, inferred-date
helper) — this plan moves *payload shape*; plan 095-Step 2 moved a helper
out of UI coupling. Neither built a collector-payload builder in
`contracts/`.

## Commands you will need

| Purpose   | Command                  | Provenance | Expected on success |
|-----------|--------------------------|------------|---------------------|
| Bootstrap | `make bootstrap`         | declared   | exit 0              |
| Lint      | `make lint`              | declared   | exit 0              |
| Type      | `make type`              | declared   | exit 0              |
| Unit      | `make test`              | declared   | pass                |
| Contracts | `make test-contracts`    | declared   | pass                |
| Boundaries | `make test-boundaries`  | declared   | pass                |

## Scope

**In scope** (the only files you should modify):

- `news_collector/contracts/adapters.py` (new `build_collector_payload`
  + `with_source_id`/`project_source` helpers; validation may live here,
  policy may not)
- `news_collector/logic/workflows/manual_ingest.py` (`_build_payload`
  becomes fetch-merge logic returning typed inputs; adapter owns the dict)
- `news_collector/logic/workflows/live_source_drift.py` (use the stamping helper)
- `news_collector/serving/api.py` (use the projector at `:396,473,1110`
  ONLY — no other serving changes)
- `tests/` contract tests for the new builders

**Out of scope** (do NOT touch, even though they look related):

- Policy values inside the payload (credibility/tier gates — plan 100 owns them).
- Any other hand-built export dicts found while searching (report them as
  a list in the final commit message for future plans; do not expand scope).
- `CollectorArticleModel` field semantics — shape move only.

## Git workflow

- Branch: `advisor/122-adapter-chokepoint`
- Commit per helper (`build_collector_payload`, then stamping/projector);
  e.g. `refactor(contracts): own manual-ingest payload shape in adapters`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 0: Baseline + plan-100 review

Run `make lint && make type && make test-contracts && make test-boundaries`.
Read plan 100's merged diff in `manual_ingest.py` so the new builder
composes with the config-gate structure (don't move policy back into the
workflow by accident).

**Verify**: gates green; you can state what 100 owns vs this plan (one sentence, commit message).

### Step 1: build_collector_payload in contracts/

Add `build_collector_payload(...)` next to `adapt_article_to_export` in
`contracts/adapters.py`: pure shape construction from typed inputs
(canonical_url, merged fields, source_config, source_metadata, counts).
No editorial judgment, no scoring, no persistence. `_build_payload`
keeps fetch-merge logic and returns typed inputs; the adapter owns the
dict shape. Prove equivalence: old-vs-new dict equality on the existing
test fixtures before switching the call site (write the parity test
first, watch it pass against the OLD code path, then switch).

**Verify**: parity test passes pre- and post-switch; `make test-contracts` green.

### Step 2: Centralize source_id stamping/projection

Add `with_source_id(record, id)` / `project_source(row)` in
`contracts/adapters.py`; replace the `live_source_drift.py:36`,
`manual_ingest.py` echoes, and `serving/api.py:396,473,1110` projections.
Serving projections are reads — keep their output shapes byte-identical
(assert in tests).

**Verify**: `make test-contracts && make test-boundaries` green; a grep
for `"source_id":` outside `contracts/` + tests returns only the (now
thin) call sites passing through the helpers — record residual hits in
the commit message.

### Step 3: Full gates

Run `make lint && make type && make test && make test-contracts && make test-boundaries`.

**Verify**: all green.

## Test plan

- Parity test: builder output equals the old inline dict on recorded
  fixtures (fails if any field mapping drifts).
- Stamping tests: `manual_` prefix rules (at `manual_ingest.py:472` —
  read it first) apply identically through the helper; serving
  projections byte-identical.
- Verification: `make test-contracts` + `make test-boundaries` green.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `grep -n '"source_id": source_id' news_collector/logic/workflows/manual_ingest.py` returns no inline-dict hits (only helper call sites)
- [ ] `build_collector_payload` exists in `contracts/adapters.py` with a parity test
- [ ] `make lint && make type && make test && make test-contracts && make test-boundaries` all pass
- [ ] `git diff --name-only 04016ca...HEAD` lists only the in-scope files
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- The code at the locations in "Current state" doesn't match the excerpts.
- The parity test fails pre-switch (the old shape differs from this
  plan's description — report the actual shape).
- Plan 100's area conflicts (sequence, don't parallelize on the same file).
- The builder needs policy knowledge to construct the dict (design smell —
  report; adapters must not author rules).
- Other hand-built export dicts tempt scope expansion (list them in the
  commit, don't fix them).
- A step's verification fails twice after a reasonable fix attempt.

## Maintenance notes

For the human/agent who owns this code after the change lands:

- New ingest paths must use `build_collector_payload` — inline
  `CollectorArticleModel` dicts in workflow code are a review rejection
  per LAW-B2.
- **Deferred:** other hand-built export dicts found during the search
  (listed in the commit message) — each is a future small plan, unblocked
  by nothing.
