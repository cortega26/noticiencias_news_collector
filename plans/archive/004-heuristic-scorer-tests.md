# Plan 004: Add unit tests for the production fallback `HeuristicScorer`

> **Executor instructions**: Follow step by step; run every verification command
> and confirm the result before moving on. Honor STOP conditions. Update this
> plan's row in `plans/README.md` when done. This plan **adds tests only** — it
> does not change `heuristic_scorer.py`.
>
> **Drift check (run first)**: `git diff --stat b30248f..HEAD -- news_collector/scoring/heuristic_scorer.py`
> If the file changed, compare the "Current state" excerpt to the live code; on
> a behavioral mismatch, STOP and report (your expected values may be wrong).

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: tests
- **Planned at**: commit `b30248f`, 2026-06-12

## Why this matters

`HeuristicScorer` is the **deterministic fallback** used to score articles when the LLM scorer is unavailable (LLM down, over budget, or circuit open). It makes real publication-ranking decisions in production, yet it has **zero tests** (`find tests -iname '*heuristic*'` is empty). Any change to its thresholds or formula could silently shift what gets published, with nothing to catch it. Because it is pure (no network, no DB), it is cheap and high-value to lock down with a regression suite.

## Current state

`news_collector/scoring/heuristic_scorer.py` (129 lines, fully self-contained, pure functions). Public entry point:

```python
class HeuristicScorer:
    def calculate_score(self, article: Article) -> float:
        # text = title + summary + content
        # Substance 35% (data density), Narrative 30% (wow*0.6 + length*0.4),
        # Relevance 20% (max(latam, readability*0.5)), Credibility 15% (structure)
        # returns round(clamp(weighted_sum, 0, 1), 4)
```

Helper behaviors to pin (read the file for exact constants):
- `_calculate_data_density(text)` (lines 61–90): counts years `19xx/20xx`, percentages, `n=`/`p<`/`×10` (weighted ×2), and numbers ≥2 digits; density = points/words; score = `min(1, density/0.02)`. Empty text → `0.0`.
- `_calculate_latam_affinity(text)` (lines 92–106): returns `0.0` if any `LOW_VALUE_KEYWORDS` present; else `1.0` if any `LATAM_KEYWORDS` present; else `0.0`.
- `_evaluate_wow_factor(text)` (lines 108–128): counts hits from a 15-word index (`breakthrough, discovery, first, new, …`); returns `min(1, hits/4)`.
- `calculate_score` clamps to `[0,1]` and rounds to 4 decimals.

`Article` is the SQLAlchemy model (`news_collector/storage/models.py:56`). The scorer reads only `article.title`, `article.summary`, `article.content`. **Tests should not touch a DB** — construct a lightweight stand-in (see Step 2).

Test conventions: existing scoring tests live in `tests/unit/scoring/` (`test_basic_scorer.py`, `test_feature_scorer.py`, …). Follow their import and parametrization style.

## Commands you will need

| Purpose | Command | Expected |
|---|---|---|
| Run the new test file | `.venv/bin/pytest tests/unit/scoring/test_heuristic_scorer.py -q` | all pass |
| Lint | `make lint` | exit 0 |
| Type | `make type` | exit 0 (note: tests dir is type-checked) |
| Coverage of the module | `.venv/bin/pytest tests/unit/scoring/test_heuristic_scorer.py --cov=news_collector/scoring/heuristic_scorer --cov-report=term-missing -q` | high coverage, see Done |

## Scope

**In scope:**
- `tests/unit/scoring/test_heuristic_scorer.py` (create)

**Out of scope:**
- `news_collector/scoring/heuristic_scorer.py` — **do not modify it.** If you believe it has a bug, note it in your report and keep the test asserting current behavior (characterization), or STOP.
- `latam_relevance.py`, the `Article` model.

## Git workflow

- Branch: `advisor/004-heuristic-scorer-tests`
- One commit; `test(scoring): …` style.
- Do NOT push or open a PR.

## Steps

### Step 1: Read the real keyword lists

Open `news_collector/scoring/latam_relevance.py` and note the actual contents of `LATAM_KEYWORDS` and `LOW_VALUE_KEYWORDS` so your test inputs deterministically trigger / avoid them. Do not hardcode guesses.

### Step 2: Build a minimal article stand-in (no DB)

The scorer only reads `.title`, `.summary`, `.content`. Use a tiny stub rather than the ORM/DB:

```python
from dataclasses import dataclass

@dataclass
class _StubArticle:
    title: str = ""
    summary: str | None = None
    content: str | None = None
```

If `make type` complains that `calculate_score` expects `Article`, either add a `# type: ignore[arg-type]` at the call site in the test or use `typing.cast(Article, stub)` — match whatever the existing scoring tests do.

### Step 3: Write characterization + edge tests

Cover, at minimum:

1. **Empty article** (`_StubArticle()`) → score is a float in `[0, 1]` (exercises empty-text paths; `_calculate_data_density("")`/empty splits must not raise `ZeroDivisionError`).
2. **Data density**: a text with several numbers/percentages/`p<0.05` scores higher on substance than a text with none. Assert the high-data score `>` the low-data score.
3. **LatAm affinity**: a text containing a real `LATAM_KEYWORDS` term (and no low-value term) yields a higher score than the same text without it. A text containing a `LOW_VALUE_KEYWORDS` term forces latam affinity to `0.0` — assert that relevance falls back to the readability path (lower or equal).
4. **Wow factor saturation**: assert the cap on the **helper directly**, not on the composite score — `scorer._evaluate_wow_factor(text_with_4_wow_words) == scorer._evaluate_wow_factor(text_with_8_wow_words) == 1.0` (the cap is `min(1, hits/4)`). Do **not** assert `calculate_score(8 wow) <= calculate_score(4 wow)`: more wow words also mean longer text, which raises `length_score`/`narrative_score`, so the composite can legitimately increase. The cap lives in `_evaluate_wow_factor` only.
5. **Clamp & rounding**: any output is `0 <= s <= 1` and `round(s, 4) == s` (4-decimal rounding).
6. **Determinism**: calling `calculate_score` twice on the same input returns the identical value.

Prefer asserting **relationships** (A > B, capped, in-range, deterministic) over brittle exact floats, except where an exact value is trivially derivable (e.g. empty-text density `0.0`).

**Verify:** `.venv/bin/pytest tests/unit/scoring/test_heuristic_scorer.py -q` → all pass.

### Step 4: Confirm coverage

**Verify:** the coverage command in the table reports the module at high line coverage. The four helper methods plus `calculate_score` should all be exercised.

## Test plan

- File: `tests/unit/scoring/test_heuristic_scorer.py`, modeled on `tests/unit/scoring/test_basic_scorer.py`.
- Cases: the six groups in Step 3 (use `pytest.mark.parametrize` where natural).
- Verification: `make test` includes the new file and stays green.

## Done criteria

ALL must hold:

- [ ] `tests/unit/scoring/test_heuristic_scorer.py` exists with ≥6 test cases
- [ ] `.venv/bin/pytest tests/unit/scoring/test_heuristic_scorer.py -q` → all pass
- [ ] Coverage of `news_collector/scoring/heuristic_scorer.py` ≥ 90% lines
- [ ] `make type` exits 0 and `make lint` exits 0
- [ ] `news_collector/scoring/heuristic_scorer.py` is **unmodified** (`git status` shows only the new test file)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report if:

- The live scorer behavior contradicts the "Current state" description (drift) — your expected relationships may be invalid.
- You find an actual bug (e.g. a crash on some realistic input, or a threshold that looks wrong). Report it as a separate finding; do not "fix" the scorer inside a test-only plan.

## Maintenance notes

- This is a **characterization** suite: it locks in *current* behavior so future formula tweaks are intentional and visible in a diff. If the NQI weights or thresholds are deliberately changed later, the failing assertions are the signal to update the tests in the same PR.
- A reviewer should confirm no test asserts a value the scorer doesn't actually produce (no aspirational assertions) and that no DB/network is touched.
