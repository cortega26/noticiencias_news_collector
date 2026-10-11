# Plan 121: Harden publication identity (single path, explicit failures, no races)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 04016ca..HEAD -- news_collector/logic/workflows/publication_identity.py news_collector/logic/workflows/publication_pipeline.py news_collector/storage/article_repository.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Depends on**: none (but read backend plan 094's merged result first —
  it unified slug extraction behind the resolver; this plan must not
  re-litigate or duplicate it)
- **Category**: bug
- **Planned at**: commit `04016ca`, 2026-10-11
- **Issue**: omit

## Why this matters

Publication identity is the load-bearing invariant of the whole system
(LAW-B5: deterministic, idempotent), and three defects cluster around it:
(1) a second slug-uniquification path in `publication_pipeline.py` with a
`uuid4` fallback makes retry output non-deterministic for the same article
— the exact failure class the identity law exists to prevent; (2) identity
persistence failures masquerade as success — `backfill_slug` swallows
exceptions (a DB outage during FS-recovery leaves the run believing
identity is locked when it is not) and `register_slug`'s `False` conflates
genuine collision with idempotent re-registration, while a bare `assert`
escapes without `error_code` for the per-item batch reporter; (3) the
filesystem collision check is check-then-act with no lock, so retry-vs-retry
or external-writer races can overwrite the same `output_filename`.
Each fix is small; together they make identity failures explicit and races
structurally impossible.

## Current state

Facts (all verified 2026-10-11):

```python
# publication_pipeline.py:72-101 — second identity path with randomness
def _unique_post_slug(*, posts_dir, date_str, base_slug, article_id):
    ...
    safe_suffix = re.sub(r"[^a-z0-9]+", "", article_id.lower())[:6]
    if not safe_suffix:
        safe_suffix = uuid.uuid4().hex[:6]   # <-- non-determinism in slug path
```

```python
# publication_identity.py:188-194 and :231-238 — check-then-act on Path.exists()
target = posts_dir / output_filename
iteration = 1
while target.exists():
    final_slug = f"{canonical_date}-{slug_part}-{iteration}"
    ...
# (in both resolve() creation mode and finalize_slug())
```

```python
# publication_identity.py:222 — bare assert escapes without error_code
assert identity.is_new, "finalize_slug only valid for creation-mode identities"
```

```python
# publication_identity.py:247-276 — failures masked
def backfill_slug(self, article_id: str, slug: str) -> None:  # returns nothing
    ...
    except Exception as e:
        logger.error("Failed to backfill canonical slug: {}", e)  # caller proceeds as recovered
def register_slug(...) -> bool:
    ...
    except Exception as e:
        logger.error(...); return False  # indistinguishable from "already exists"
```

```python
# article_repository.py:741-770 — set_canonical_slug: False covers BOTH
# collision-with-different-article AND overwrite-refusal; IntegrityError path
# distinguishes same-row retry (True) from genuine collision (False + warning).
```

Callers: `resolve:161-162` proceeds after `backfill_slug` regardless;
`publication_pipeline.py:878` batch loop is sequential and
`publication_run_workflow.py:380` delegates to it — so the FS race window
is retry-vs-retry/external-writer, not intra-batch (keep single-process
behavior identical per ADR-0011 local/hosted split).

Repo conventions: LAW-B5 (deterministic identity; migration plan explicit
before identity-logic changes); LAW-B6 (per-item explicit outcomes);
LAW-B7 (no swallowed exceptions); `make test-boundaries` for workflow
changes; plan 094 merged "engine method now thin delegate" — verify its
current shape before touching adjacent code.

## Commands you will need

| Purpose   | Command                  | Provenance | Expected on success |
|-----------|--------------------------|------------|---------------------|
| Bootstrap | `make bootstrap`         | declared   | exit 0              |
| Lint      | `make lint`              | declared   | exit 0              |
| Type      | `make type`              | declared   | exit 0              |
| Unit      | `make test`              | declared   | pass                |
| Boundaries | `make test-boundaries`  | declared   | pass                |
| Quality gate | `make quality-gate`   | declared   | pass (publication-area change) |

## Scope

**In scope** (the only files you should modify):

- `news_collector/logic/workflows/publication_pipeline.py` (delete
  `_unique_post_slug`; route through the resolver)
- `news_collector/logic/workflows/publication_identity.py`
  (tri-state/explicit outcomes; atomic resolve-vs-write; typed error)
- `tests/` (identity tests: collision-vs-reregistration split, backfill
  failure propagation, concurrency test for the atomic path)

**Out of scope** (do NOT touch, even though they look related):

- `article_repository.py:set_canonical_slug` internals — already correct;
  read-only reference.
- `refinery_manifest.json` index shape — no change.
- Existing published slugs/filenames — no migration in this plan (any
  slug-output change needs a LAW-B5 migration note first → STOP).
- Plan 094's unified extraction — do not re-litigate; build on it.

## Git workflow

- Branch: `advisor/121-identity-hardening`
- Commit per step; e.g. `fix(identity): route pipeline slug through PublicationIdentityResolver`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 0: Baseline + plan-094 review

Run `make lint && make type && make test-boundaries`. Read plan 094's
merged code (the thin-delegate engine method + the 12 committed parity
cases) so this plan's changes compose with it.

**Verify**: gates green; you can state in one sentence what 094 owns vs
what this plan owns (write it in the first commit message).

### Step 1: Delete the second slug path

Delete `_unique_post_slug`; call `PublicationIdentityResolver` at its call
site. Fail closed when `article_id` is empty (explicit error, e.g.
`UndatedArticleError`-style) instead of minting `uuid4` randomness. Per
LAW-B5, if any existing post's slug/filename would change under the
resolver, STOP — that needs a migration plan first.

**Verify**: `grep -rn "uuid" news_collector/logic/workflows/publication_pipeline.py`
returns no matches; `make test-boundaries` passes; a probe with empty
`article_id` fails explicitly (no random slug).

### Step 2: Make persistence outcomes explicit

1. `backfill_slug` returns success (`bool`); its caller in `resolve`
   branches on it (failure → explicit per-item error, not silent recovery).
2. Split `register_slug` outcomes so genuine collision is
   distinguishable from idempotent re-registration (tri-state or typed
   error — match the file's existing style; the repository layer already
   distinguishes them, so plumb it through, don't re-derive it).
3. Replace the bare `assert identity.is_new` with a typed error carrying
   `error_code`/`public_message` for the batch reporter.

**Verify**: new tests assert all three legs (created/exists/collision;
backfill-fail propagates; finalize-on-non-new raises typed error);
`make test-boundaries` passes.

### Step 3: Close the FS check-then-act race

Resolve-then-create atomically (e.g. `O_EXCL` create or DB slug
reservation before FS write) instead of `Path.exists()` loops in both
`resolve` creation mode and `finalize_slug`. Keep single-process behavior
identical (ADR-0011 split respected). Add a concurrency test (two
resolves, same canonical input → exactly one wins, the other gets an
explicit collision outcome, no overwrite).

**Verify**: concurrency test passes; `make test-boundaries` passes;
sequential behavior unchanged (existing tests green unmodified).

### Step 4: Full gates

Run `make lint && make type && make test && make test-boundaries && make quality-gate`.

**Verify**: all green.

## Test plan

- Identity tests: reregistration-returns-exists vs genuine-collision
  (using two article ids → same slug); backfill-DB-outage propagates;
  finalize-on-used-identity raises typed error with `error_code`;
  concurrent same-slug resolves → one winner + explicit loser outcome.
- Model on plan 094's 12 committed parity cases (extend that file if it fits).
- Verification: `make test-boundaries` green.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `grep -rn "_unique_post_slug" news_collector/` returns no matches
- [ ] `grep -n "uuid" news_collector/logic/workflows/publication_pipeline.py` returns no matches
- [ ] `grep -n "^    assert " news_collector/logic/workflows/publication_identity.py` returns no matches
- [ ] `register_slug` outcomes distinguish collision from re-registration (test proves it)
- [ ] `make lint && make type && make test && make test-boundaries && make quality-gate` all pass
- [ ] `git diff --name-only 04016ca...HEAD` lists only the in-scope files
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- The code at the locations in "Current state" doesn't match the excerpts.
- Routing through the resolver would change any existing slug/filename
  (LAW-B5 migration needed — report, don't migrate here).
- Plan 094's area conflicts with this plan's edits (sequence, don't parallelize).
- The atomic-create approach doesn't fit the hosted/local split of ADR-0011
  (report the mismatch).
- A step's verification fails twice after a reasonable fix attempt.

## Maintenance notes

For the human/agent who owns this code after the change lands:

- Identity has exactly one path now (`PublicationIdentityResolver`) — new
  slug/filename logic anywhere else is a review rejection per LAW-B5/B9.
- If the FS/DB split ever moves to concurrent batch items, the Step-3
  concurrency test is the guard — extend it, don't delete it.
- **Deferred:** promoting `refinery_id` to an indexed column (see plan 124
  — it removes the full-scan transitions that make races more likely).
