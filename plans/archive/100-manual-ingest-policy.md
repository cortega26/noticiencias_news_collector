# Plan 100: Move manual-ingest source policy out of the workflow (credibility, tier, word-gate, date inference)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat e77a039..HEAD -- news_collector/logic/workflows/manual_ingest.py news_collector/logic/workflows/publication_identity.py tests/unit/logic/workflows/ noticiencias/config_schema.py config.toml`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P3
- **Effort**: M
- **Risk**: MED
- **Depends on**: none (coordinate with 094 — identity semantics must not shift under you; 094 is behavior-preserving by construction)
- **Category**: tech-debt
- **Planned at**: commit `e77a039`, 2026-09-16

## Why this matters

`manual_ingest.py` authors policy inside orchestration, violating LAW-B3 three
ways: it synthesizes `source_id`, hardcodes `credibility_score: 0.5` + tier
`"D"` for invented sources, enforces its own word-count gate, and — most
seriously — invents `published_date = now()` for dateless URLs while
`PublicationIdentityResolver` quarantines undated articles instead of inventing
dates (LAW-B5 tension: the same article gets different canonical identity
depending on entry path). After this plan, the workflow keeps host→source
matching mechanics, but credibility/tier defaults, the word gate, and the
date-inference rule live in one policy/config owner shared with the resolver.

## Current state

The relevant files, each with one line on its role:

- `news_collector/logic/workflows/manual_ingest.py` — `_resolve_or_create_source` (lines 421-468), `_build_payload` date inference (lines 556-559), word gate (lines 590-599)
- `news_collector/logic/workflows/publication_identity.py` — quarantine path `_derive_date` (lines 329-352)
- `noticiencias/config_schema.py` + `config.toml` — candidate home for the tunables

Excerpts of the code as it exists today:

`manual_ingest.py:433-453` — invented source with hardcoded policy:

```python
source_id = f"manual_{normalized_host.replace('.', '_')}"
...
source_cfg = {
    "name": normalized_host,
    "url": base_url,
    "credibility_score": 0.5,
    ...
    "tier": "D",
    ...
}
```

`manual_ingest.py:556-559` — clock-invented canonical date:

```python
inferred_published_date = False
if not merged["published_date"]:
    merged["published_date"] = datetime.now(timezone.utc)
    inferred_published_date = True
```

`manual_ingest.py:590-599` — workflow-local word gate (`MANUAL_INGEST_MIN_WORDS = 80` at line 30; `40` summary-only branch on line 592):

```python
word_basis = content or summary or ""
word_count = max(1, _word_count(word_basis))
minimum_words = 40 if not content and summary else MANUAL_INGEST_MIN_WORDS
if word_count < minimum_words:
    return None, {
        "error_code": "source_unusable",
        ...
```

`publication_identity.py:329-352` — the resolver quarantines (`UndatedArticleError`) where ingest invents.

Repo conventions that apply here:

- LAW-B3: thresholds/policy live in policy modules or config, not orchestration.
- LAW-B5: any identity-logic change needs an explicit migration/compatibility note BEFORE code lands — the `inferred_published_date` flag and already-persisted manual rows are the compatibility surface.
- Config changes (`config_schema.py`/`config.toml`) trigger `make config-docs-check`.

## Commands you will need

| Purpose   | Command                  | Provenance | Expected on success |
|-----------|--------------------------|------------|---------------------|
| Install   | `make bootstrap`         | declared   | exit 0 |
| Lint      | `make lint`              | declared   | exit 0 |
| Type      | `make type`              | declared   | exit 0, ratchet passes |
| Tests     | `make test`              | declared   | all pass |
| Boundaries| `make test-boundaries`   | declared   | all pass |
| ConfigDocs| `make config-docs-check` | declared   | exit 0 (if schema touched) |

## Scope

**In scope** (the only files you should modify):

- `news_collector/logic/workflows/manual_ingest.py` (read policy from owner; keep matching mechanics)
- ONE policy owner — prefer config (`noticiencias/config_schema.py` + `config.toml` + `docs/config_fields.md` regen via `make config-docs`) for the numeric tunables (credibility, word minimums); the date-inference rule goes next to `PublicationIdentityResolver` as an explicit `published_date_inferred` handling both sides honor
- `tests/unit/logic/workflows/` (manual-ingest policy tests)

**Out of scope** (do NOT touch, even though they look related):

- Feed-collector source scoring/tiers — different owner, different lifecycle.
- The resolver's quarantine semantics — plan 089 territory; this plan only routes the manual path INTO the documented handling.
- HTML/headless collectors' own `now()` fallbacks (unvetted investigate item) — report, don't bundle.

## Git workflow

- Branch: `advisor/100-manual-ingest-policy`
- Conventional commits, e.g. `refactor(ingest): externalize manual source policy`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 0: Establish a green baseline

Run `Install`, then `Lint`, `Type`, `Tests` on the unmodified checkout. On any
`declared`-command failure on the clean tree: **STOP and report** with exact output.

**Verify**: all commands match their expected results on the unmodified checkout.

### Step 1: Trace the inferred-date compatibility surface

1. Where does `inferred_published_date` go after line 559? Grep it — is it persisted on the article row/metadata, passed to the resolver, or dropped? If persisted, already-stored manual rows carry clock-invented `published_date`s: record how many such rows could exist (query pattern, don't need exact count — the migration note needs the shape, not the census).
2. Does ANY other path read `credibility_score == 0.5` / `tier == "D"` / `manual_only` as a signal (scoring weights, triage filters)? Grep all three.
3. Decide the date rule and RECORD it before coding (this is the LAW-B5 migration note, one paragraph in the commit message + plan report): recommended — manual ingest marks `published_date_inferred=true` in metadata and the resolver treats inferred dates as explicit input (preserving current downstream behavior) while the *default* for new dateless manuals becomes quarantine-with-inference-offered; OR keep inference but move the rule + flag into the shared owner so both paths agree. Either is acceptable ONLY if stated upfront and tested. If persisted rows make any option unsafe, STOP and report.

**Verify**: written migration note + grep lists. No code changed yet.

### Step 2: Externalize the tunables

1. Move `credibility_score` default, tier default, `MANUAL_INGEST_MIN_WORDS`, and the 40-word summary-only branch value into config (new `[manual_ingest]`-style section in `config_schema.py` + `config.toml` defaults matching TODAY's values exactly) OR a narrow policy module if config is the wrong home (decide by reading how sibling ingestion tunables like `recent_days_threshold` are owned — follow that precedent, don't invent).
2. Workflow reads them from the injected `cfg`/policy owner; no literals remain in `manual_ingest.py` (grep `0.5`, `"D"`, `80`, `40` in the file after — each remaining hit must be justified in the commit message).
3. `make config-docs` regen if schema touched; `make config-docs-check` green.

**Verify**: behavior-identical tunables (values unchanged, only the owner moved); config-docs gate green if applicable.

### Step 3: Route date inference through the shared rule

Implement the Step 1 decision: the workflow no longer calls `datetime.now()` inline for identity purposes — it invokes the shared inference rule (or explicit quarantine path) so manual and feed paths agree on what "undated" means. The `inferred_published_date` flag must survive end-to-end wherever it is consumed today.

**Verify**: `.venv/bin/python -m pytest tests/unit/logic/workflows/ -q` → pass; add policy tests: custom credibility default flows into created sources; word-gate honors configured minimums; dateless manual follows the documented rule (inference-flagged or quarantined per Step 1).

### Step 4: Run the full gates

**Verify**: `make lint && make type && make test && make test-boundaries` → all exit 0 (+ `config-docs-check` if schema touched).

## Test plan

- New policy tests (defaults flow-through, word-gate boundaries incl. the 40-word summary branch, dateless-manual rule).
- Existing manual-ingest + identity + workflow suites green (no identity value for previously-successful publishes may change — the Step 1 note is the proof artifact).

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `make lint`, `make type`, `make test`, `make test-boundaries` all exit 0 (plus `config-docs-check` if schema touched)
- [ ] No policy literals remain in `manual_ingest.py` (`credibility_score`, tier, word minimums, `datetime.now` for identity — grep)
- [ ] LAW-B5 migration note recorded in the commit message for the date rule
- [ ] New policy tests exist and pass
- [ ] `git diff --name-only e77a039...HEAD` lists only the in-scope files
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- The code at the locations in "Current state" doesn't match the excerpts.
- Step 1 shows persisted manual rows depend on invisible inference in a way no compatible rule can preserve.
- Sibling-tunable precedent points at a different owner than config AND a different one than a policy module (report the options).
- The fix appears to require resolver quarantine changes (plan 089 owns that boundary).
- A step's verification fails twice after a reasonable fix attempt.

## Maintenance notes

- Future source-default changes now happen in config/policy review, not workflow review — update the PR checklist mentally, not in code.
- Reviewers: the date-rule decision is the whole plan; everything else is moving literals.
- **Deferred:** HTML/headless `now()` fallbacks unification — same theme, needs source-by-source datelessness evidence first.
