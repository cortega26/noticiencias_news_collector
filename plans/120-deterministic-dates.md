# Plan 120: Make publication dates deterministic (undated, naive, calendar)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 04016ca..HEAD -- news_collector/collectors/html_collector.py news_collector/collectors/rss_collector.py news_collector/collectors/base_collector.py news_collector/collectors/admission.py news_collector/contracts/frontend_schema.py news_collector/utils/datetime_utils.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: LOW
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `04016ca`, 2026-10-11
- **Issue**: omit

## Why this matters

Publication identity (LAW-B5) derives the canonical date from feed dates,
and three date-handling defects make it non-deterministic or wrong:
(1) undated HTML articles get the collector's wall-clock time baked in as
`published_date`, so retries mint different canonical dates/slugs for the
same article and bypass the `UndatedArticleError` quarantine the identity
layer deliberately enforces; (2) naive feed timestamps are silently labeled
UTC via `replace(tzinfo=...)` in three collectors, shifting non-UTC
publishers' dates by hours (potentially the canonical day/slug); a correct
`ensure_timezone` helper already exists and is bypassed; (3) both contracts
accept `review_date`/`corrected_at` strings matching `YYYY-MM-DD` shape
that are not real calendar dates (`2026-13-40` passes), poisoning display
and correction-pair checks with nonsense.

## Current state

Facts (all verified 2026-10-11):

```python
# html_collector.py:303 — wall-clock invention for undated articles
"published_date": raw.get("date") or datetime.now(timezone.utc),
```

```python
# rss_collector.py:834; base_collector.py:718; admission.py:66 — naive labeled UTC
published = published.replace(tzinfo=timezone.utc)
dt = dt.replace(tzinfo=timezone.utc)
published = published.replace(tzinfo=timezone.utc)
```

```python
# utils/datetime_utils.py:41-59 — the correct helper, bypassed by the above
# ensure_timezone(...) (uses calendar.timegm path); verify its exact signature first.
```

```python
# frontend_schema.py:207-210 — shape-only validation
review_date: Optional[str] = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
corrected_at: Optional[str] = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
```

Identity-layer context (read-only — do NOT change in this plan):
`publication_identity.py:99-100` restricts clock use to manual ingest only;
`:358-389` `_derive_date` raises `UndatedArticleError` for the same case
the HTML collector papers over; `headless_collector.py:285-286` has the
same `or datetime.now` pattern (include it if the identical shape is
confirmed — see Step 1).

Repo conventions: LAW-B5 (deterministic identity — no runtime time in
identity paths); LAW-B4 (I/O at edges, policy pure); `make test-boundaries`
for collector/orchestration changes. Prior related: plan 089 made
whitespace-only dates count as missing in `_derive_date` (adjacent, not
overlapping).

## Commands you will need

| Purpose   | Command                  | Provenance | Expected on success |
|-----------|--------------------------|------------|---------------------|
| Bootstrap | `make bootstrap`         | declared   | exit 0              |
| Lint      | `make lint`              | declared   | exit 0              |
| Type      | `make type`              | declared   | exit 0              |
| Unit      | `make test`              | declared   | pass                |
| Boundaries | `make test-boundaries`  | declared   | pass                |
| Contracts | `make test-contracts`    | declared   | pass                |

## Scope

**In scope** (the only files you should modify):

- `news_collector/collectors/html_collector.py` (propagate `None`, drop wall-clock default)
- `news_collector/collectors/headless_collector.py` (same fix ONLY if the
  identical `or datetime.now` shape is confirmed at `:285-286`)
- `news_collector/collectors/rss_collector.py`, `base_collector.py`,
  `admission.py` (route naive dates through `ensure_timezone`)
- `news_collector/contracts/frontend_schema.py` (calendar-date validators
  for the two fields — small addition; coordinate with plan 118 if it is
  in flight on the same file: sequence after it, don't parallelize)
- `tests/` (collector date tests + contract calendar tests)

**Out of scope** (do NOT touch, even though they look related):

- `publication_identity.py` `_derive_date`/quarantine logic — it is
  already correct; this plan feeds it `None` instead of fake dates.
- Frontend `content.config.ts` calendar check — the frontend accepts the
  same shape-only regex; file it as a follow-up note (see Maintenance),
  don't cross repos here.
- Per-source timezone documentation beyond a code comment naming the
  assumption (feed tz vs UTC) in source metadata.

## Git workflow

- Branch: `advisor/120-deterministic-dates`
- Commit per step; e.g. `fix(collectors): quarantine undated HTML articles instead of clock-stamping`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 0: Establish a green baseline

Run `make lint && make type && make test-boundaries` on the unmodified
checkout. Record any pre-existing reds (working tree was dirty at plan
time — you are isolated; record, don't fix).

**Verify**: gates green at baseline, or pre-existing reds recorded with a STOP-and-report.

### Step 1: Quarantine undated articles instead of clock-stamping

1. Confirm the `headless_collector.py:285-286` shape matches; if yes,
   include it, if no, record why not and skip it.
2. In `html_collector.py` (and headless if confirmed), propagate `None`
   when `raw.get("date")` is absent and let `_derive_date` raise
   `UndatedArticleError` with the existing per-item continue-on-error
   handling. Adjust the 1–2 tests that assert the clock-stamped behavior
   (they encode the bug — rewrite them to assert quarantine + per-item
   reporting, and say so in the commit message).

**Verify**: `make test-boundaries` passes; a probe article with no date
quarantines with an explicit per-item outcome instead of publishing with
today's date.

### Step 2: Centralize naive-datetime handling on ensure_timezone

Read `utils/datetime_utils.py:41-59` first. Route all naive feed dates in
`rss_collector.py`, `base_collector.py`, `admission.py` through
`ensure_timezone`; record the assumption (feed tz vs UTC) in source
metadata per the existing pattern instead of silent `replace`. Keep retry/
backoff-window comparisons (`next_retry`, `last_checked` sites at
`rss_collector.py:192`, `base_collector.py:789,812`) untouched unless they
consume the same naive values — if they do, say so in the commit; if the
blast radius exceeds the three call sites, STOP and report.

**Verify**: `make test-boundaries` passes; new tests assert a naive
non-UTC timestamp normalizes identically regardless of host timezone
(run the test file with `TZ=Pacific/Kiritimati` and `TZ=America/New_York`
to prove host-independence).

### Step 3: Reject non-calendar review/correction dates

After the shape regex, parse with `date.fromisoformat` (backend) in field
validators for `review_date`/`corrected_at`; emit the same field-scoped
error shape. Add contract tests (`2026-13-40`, `2026-02-30` rejected;
`2026-02-28` accepted).

**Verify**: `make test-contracts` passes with the new cases.

### Step 4: Full gates

Run `make lint && make type && make test && make test-boundaries && make test-contracts`.

**Verify**: all green.

## Test plan

- Collector tests: undated HTML article → quarantine outcome (not a
  clock-stamped publish); naive feed datetime → host-TZ-independent
  normalization (two-TZ run).
- Contract tests: non-calendar dates rejected (2 cases), valid kept.
- Verification: `make test-boundaries` + `make test-contracts` green.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `grep -n "or datetime.now(timezone.utc)" news_collector/collectors/html_collector.py` returns no matches (and headless too, if included)
- [ ] `grep -n "replace(tzinfo=timezone.utc)" news_collector/collectors/rss_collector.py news_collector/collectors/base_collector.py news_collector/collectors/admission.py` returns no matches (except retry/backoff sites explicitly documented in the commit)
- [ ] `2026-13-40` fails `AstroPost` validation (probe or test)
- [ ] `make lint && make type && make test && make test-boundaries && make test-contracts` all pass
- [ ] `git diff --name-only 04016ca...HEAD` lists only the in-scope files
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- The code at the locations in "Current state" doesn't match the excerpts.
- Quarantining undated HTML articles crashes a batch instead of a per-item
  skip (continue-on-error wiring missing — report, don't rewire orchestration).
- Step-2 blast radius exceeds the three call sites (retry/backoff
  entanglement — report).
- Plan 118 is concurrently editing `frontend_schema.py` (sequence, don't parallelize).
- Undated-article counts change pipeline output in a way operators must
  know about (they will — quarantining is correct but visible; note the
  expected count shift in the commit message for the operator).
- A step's verification fails twice after a reasonable fix attempt.

## Maintenance notes

For the human/agent who owns this code after the change lands:

- New collectors must route dates through `ensure_timezone` and propagate
  `None` for missing dates — add both to the review checklist (the two
  failure modes recur per collector).
- **Deferred:** frontend `content.config.ts` calendar check for the same
  two fields (small; needs a cross-repo touch — file it with the next
  schema change, don't open a second front for it).
