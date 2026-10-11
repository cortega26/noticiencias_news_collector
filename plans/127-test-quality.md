# Plan 127: Public pagination tests, deterministic clocks, honest doubles

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 04016ca..HEAD -- news_collector/serving/api.py tests/test_serving_admin_api.py tests/test_source_reliability.py tests/conftest.py tests/test_quality_contract.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: LOW
- **Depends on**: none
- **Category**: tests
- **Planned at**: commit `04016ca`, 2026-10-11
- **Issue**: omit

## Why this matters

Three test-quality gaps, all additive and independent: the public
paginated API surface (documented deterministic-sort + opaque-cursor
invariant) has no boundary test — only the admin endpoint has a
determinism test — so a cursor-encoding regression ships to consumers;
real `time.sleep` polling tests plus wall-clock fixtures make the suite
slow and time-bomb-prone (the repo built `make test-timeshift` for exactly
this but gates nothing on it); and mock-heavy suites assert on doubles
rather than behavior, so production wiring rots invisibly (the repo's own
`spec-test-suite-audit.md` Phase 0 built detection tooling with no
recorded remediation pass). Test-only changes throughout.

## Current state

Facts (all verified 2026-10-11):

```python
# serving/api.py:297-310 — _decode_cursor raises 400 on malformed cursors
# serving/api.py:1020-1056 + :1251-1286 — public + admin paginated endpoints
# sharing score/date/id cursor logic
# tests/test_serving_admin_api.py:473 — test_admin_articles_pagination_is_deterministic
# (admin only); tests/unit/serving/ holds only dashboard-health/port/
# image-security/poll-filter tests — nothing for public pagination.
```

```python
# tests/test_serving_admin_api.py:908,1134,1182,2717 — time.sleep(0.1) polling tests
# tests/test_source_reliability.py:67 — time.sleep(0.05)
# tests/conftest.py:45,54; tests/test_serving_api.py:22,145;
# tests/test_quality_contract.py:56 (+ dozens of datetime.now(timezone.utc)
# call sites) — wall-clock fixtures; Makefile:408 test-timeshift (+120d) opt-in only.
```

```python
# tests/test_quality_contract.py:1-20 (verified):
from unittest.mock import MagicMock, patch
...
@patch("news_collector.collectors.rss_collector.enrichment_pipeline")
class TestQualityContract:
    @pytest.fixture
    def collector(self):
        db_manager = MagicMock()
        db_manager.save_article.return_value = MagicMock()
        return RSSCollector(db_manager, config=load_config())
# whole collaborators (db, git, editor, system.validator) replaced by MagicMock
# in test_editorial_policy / test_validation_loop / decompose_refinery fixtures.
# spec-test-suite-audit.md:7-12 — Phase 0 detection tooling exists
# (scripts/test_suite_audit.py for assertion-less/mock-heavy/no-code-touching tests).
```

Boundary conditions: the fifth-pass ledger deferred "refinery-engine
de-mocking" as second-tier — this plan MUST NOT touch refinery-engine
doubles (STOP if the audit list's top items are all refinery-engine;
work the next seams instead). `make test-audit` is the ranking tool —
run it first and work top-down.

Repo conventions: `docs/AGENTS.md` §4.1 (mock only at the boundary —
network, LLM, clock, tmp-external filesystem; real SQLite + tmp_path
preferred); §5 (relative dates, never absolute); deterministic pagination
is a documented serving invariant.

## Commands you will need

| Purpose   | Command                  | Provenance | Expected on success |
|-----------|--------------------------|------------|---------------------|
| Bootstrap | `make bootstrap`         | declared   | exit 0              |
| Unit      | `make test`              | declared   | pass                |
| Audit     | `make test-audit` (verify target name in Makefile first — spec references it) | declared | report produced |
| Timeshift | `make test-timeshift`    | declared   | pass (periodic check) |

## Scope

**In scope** (tests only, plus minimal fixtures):

- `tests/` new pagination tests (public endpoint walk + invalid cursor)
- `tests/test_serving_admin_api.py`, `tests/test_source_reliability.py`
  (sleep → deterministic waits)
- Wall-clock fixtures in the worst files first (freeze/fake-clock)
- Mock-heavy non-refinery seams (adapters, publication identity first —
  real SQLite/real temp files over mocked storage)

**Out of scope** (do NOT touch, even though they look related):

- `tests/` for refinery-engine doubles — fifth-pass deferred; record, don't touch.
- Production code — if tightening a test exposes real interface drift,
  STOP and report (that's a production fix needing its own plan, per the
  MED risk note).
- Making `test-timeshift` a per-PR gate — periodic only.

## Git workflow

- Branch: `advisor/127-test-quality`
- Commit per item (pagination, clocks, doubles).
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 0: Baseline + audit ranking

Run `make test` green at baseline. Run `make test-audit` (if the target
doesn't exist, use `scripts/test_suite_audit.py` directly per the spec —
verify the path first) and record the mock-heavy list top-down.

**Verify**: baseline green; ranked list in hand.

### Step 1: Public pagination tests

Mirror the admin determinism test against the PUBLIC articles endpoint:
seed N articles, walk `next_cursor` to exhaustion asserting deterministic
order + full coverage; assert 400 on garbage cursor (`_decode_cursor`
path); add empty-page case. First verify no other file already covers the
public path (`grep -rln "next_cursor" tests/ | head` — if coverage exists,
extend it instead of duplicating).

**Verify**: new tests pass; `make test` passes.

### Step 2: Deterministic clocks

Convert the `time.sleep` polling tests (4 sites in
`test_serving_admin_api.py` + 1 in `test_source_reliability.py`) to
deterministic waits; freeze `datetime.now` fixtures in the worst files
first (conftest + serving api tests). Do NOT over-apply frozen clocks
where tz behavior is under test (report any such site and leave it).

**Verify**: converted tests pass consistently (run each file 3×);
`make test-timeshift` passes as a periodic check (record result; expiry-gate
failures like the pip-audit allowlist are legitimate timeshift failures —
report, don't "fix").

### Step 3: Honest doubles (non-refinery seams)

Work the `make test-audit` mock-heavy list top-down, SKIPPING anything in
refinery-engine paths (deferred). Replace doubles with fakes/contracts on
the highest-risk remaining seams first (adapters, publication identity):
real SQLite, real temp files; mock only at network/LLM/clock/filesystem
boundaries. If a tightening exposes real interface drift → STOP that item
and report (production plan needed).

**Verify**: converted tests pass; `make test` passes; audit list shrinks
(record before/after counts in the commit message).

## Test plan

- New pagination tests (walk-to-exhaustion + 400-on-garbage + empty page).
- Converted clock tests (3× stability run each).
- Converted double tests (assert on behavior/outcomes, not mock calls).
- Verification: `make test` + `make test-timeshift` green.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] Public-endpoint pagination walk + invalid-cursor tests exist and pass
- [ ] No `time.sleep(` remains in the five named test sites
- [ ] `make test-audit` mock-heavy count decreased (record numbers)
- [ ] `make test` and `make test-timeshift` pass
- [ ] Zero production files changed (`git diff --name-only 04016ca...HEAD -- news_collector/ apps/ scripts/` is empty)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- The code at the locations in "Current state" doesn't match the excerpts.
- Public pagination is already covered elsewhere (extend, don't duplicate).
- The audit list's top items are all refinery-engine (deferred — work the
  next seams or close the step with the ranking recorded).
- Tightening a test exposes real production drift (report; needs its own plan).
- Frozen clocks would mask tz behavior at a site (leave it, report it).
- A step's verification fails twice after a reasonable fix attempt.

## Maintenance notes

For the human/agent who owns this code after the change lands:

- New tests must use relative dates (`now - timedelta(...)`) and
  deterministic waits — the §4.1 review criteria (no bare smoke, no
  asserting on fakes, no implementation-pinning) apply to every new test.
- **Deferred:** refinery-engine de-mocking (fifth-pass decision stands);
  per-PR `test-timeshift` gating (periodic is enough).
