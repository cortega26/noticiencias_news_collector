# Plan 003: Fix editorial approval gate — replace substring match with exact/normalized match

> **Executor instructions**: Follow step by step; run every verification command
> and confirm the expected result before moving on. Honor STOP conditions.
> Update this plan's row in `plans/README.md` when done.
>
> **Drift check (run first)**: `git diff --stat b30248f..HEAD -- news_collector/editorial/council.py`
> If the file changed, compare the "Current state" excerpt to the live code; on
> a mismatch, STOP.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `b30248f`, 2026-06-12

## Why this matters

The editorial council decides whether an article is approved for publication. It checks the LLM's `editor_approval` field with a **substring** test: `"si" in editor_approval`. Because `"si"` is a substring of `"sin"`, an editor reply like `"Sin valor periodístico, no"` (a clear rejection) satisfies the approval condition. The expected replies are `"Sí, es Noticiencias"` / `"No, requiere cambios"`, so any rejection phrased with a word containing "si"/"sí" can flip the gate the wrong way. This is the same class of fragile-string-parsing bug this codebase has been bitten by before; the fix is cheap and the failure mode (publishing rejected content, or rejecting approved content) is expensive.

## Current state

```python
# news_collector/editorial/council.py:131-140  (inside _parse_verdict)
editor_approval = data.get("editor_approval", "").lower()
is_editor_approved = "sí" in editor_approval or "si" in editor_approval   # <-- lines 132-133, the bug

# Rule of Publication
# - Promedio >= 3.5
# - Ningún rol puntúa < 2
# - Editor responde explícitamente "Sí..."
approved = average >= 3.5 and min_score >= 2.0 and is_editor_approved
```

Facts:
- `editor_approval` is the raw LLM string, already lowercased.
- The expected affirmative is `"Sí, es Noticiencias"` and the expected negative is `"No, requiere cambios"` (the council prompt instructs these two exact phrases — confirm by reading the prompt the council uses; search `editor_approval` / `Noticiencias` in `news_collector/config/prompts.py` and any prompt referenced by `council.py`).
- The gate `approved` is an AND of three conditions, so this is necessary-but-not-sufficient — but it is still load-bearing and currently wrong.

## Commands you will need

| Purpose | Command | Expected |
|---|---|---|
| Council tests | `.venv/bin/pytest tests -k council -q` | all pass |
| Lint | `make lint` | exit 0 |
| Type | `make type` | exit 0 |
| Fast suite | `make test` | all pass |

(First locate existing council coverage: `find tests -iname '*council*'; grep -rln "editor_approval\|_parse_verdict\|CouncilResult" tests/`.)

## Scope

**In scope:**
- `news_collector/editorial/council.py` — the approval predicate only
- the council test file (add cases); create `tests/unit/editorial/test_council_verdict.py` if no focused test exists

**Out of scope:**
- The scoring/average/min_score logic in `_parse_verdict` — leave unchanged.
- The council prompt text — do not change prompts here.
- Any LLM-call/network code.

## Git workflow

- Branch: `advisor/003-council-exact-approval`
- One commit; `fix(editor): …` style.
- Do NOT push or open a PR.

## Steps

### Step 1: Replace the substring predicate with a robust affirmative check

The goal: approve **only** when the editor explicitly affirms, and never let a negative phrase that happens to contain "si"/"sín" pass.

A plain `startswith("si")` is **insufficient** — `"sin".startswith("si")` is `True`, so `"sin valor periodístico, no"` would still approve. You must use a **word-boundary** match. Use exactly this:

```python
import re  # add at top of council.py if not already imported
...
editor_approval = data.get("editor_approval", "").strip().lower()
is_negative = bool(re.match(r"\s*no\b", editor_approval)) or "requiere cambios" in editor_approval
is_affirmative = bool(re.match(r"\s*s[ií]\b", editor_approval)) and not is_negative
is_editor_approved = is_affirmative
```

Why this is correct (the `\b` after `s[ií]` requires a word boundary):
- `re.match(r"\s*s[ií]\b", "sí, es noticiencias")` → matches → approve ✓
- `"si"` → matches → approve ✓
- `"sin valor periodístico, no"` → **no match** (`i` is followed by `n`, no boundary) → not approved ✓ (the regression case)
- `"no, requiere cambios"` → no match → not approved ✓

Add `import re` at the top of `council.py` if it is not already imported.

**Verify:** `grep -n '"si" in editor_approval' news_collector/editorial/council.py` → no matches.

### Step 2: Add regression tests for the verdict logic

Add a focused test that calls `_parse_verdict` (or the public method that wraps it) with crafted `data` dicts and asserts approval:

- `editor_approval="Sí, es Noticiencias"` + good scores → `is_approved True`
- `editor_approval="No, requiere cambios"` + good scores → `is_approved False`
- `editor_approval="Sin valor periodístico, no"` + good scores → `is_approved False` (**the regression case**)
- `editor_approval="si"` + good scores → `is_approved True`
- good `editor_approval` but `min_score=1.0` → `is_approved False` (AND still holds)

To build valid `data`, mirror the structure `_parse_verdict` reads: `data["council_assessments"]` is a list of `{"role": ..., "score": ...}`, and `data["editor_approval"]` is the string. Construct assessments that yield `average >= 3.5` and `min_score >= 2.0` for the positive cases.

**Verify:** `.venv/bin/pytest tests -k council -q` → all pass, including the 5 new cases.

## Test plan

- New tests in `tests/unit/editorial/test_council_verdict.py` (or the existing council test file): the five cases above, with the `"Sin valor… no"` case as the explicit regression guard.
- Pattern: follow an existing editorial test (`find tests/unit/editorial -name 'test_*.py'`) for fixture/import style.
- Verification: `make test` → all pass.

## Done criteria

ALL must hold:

- [ ] `grep -n '"si" in editor_approval' news_collector/editorial/council.py` → no matches
- [ ] The `"Sin valor periodístico, no"` test asserts `is_approved is False` and passes
- [ ] `make type` exits 0
- [ ] `make test` exits 0; new council verdict tests exist and pass
- [ ] Only `council.py` and the council test file modified (`git status`)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report if:

- The live predicate no longer matches the excerpt (drift).
- The council prompt does **not** actually instruct `"Sí, es Noticiencias"` / `"No, requiere cambios"` — if the expected phrases differ, report what they are before finalizing the regex, so the match aligns with reality.
- A test reveals other code depends on the loose substring behavior.

## Maintenance notes

- The durable fix would be to have the LLM return a structured boolean (`editor_approved: true/false`) in JSON rather than free text; if the council prompt/schema is revisited later, prefer that and delete the string parsing. Note this as deferred follow-up.
- A reviewer should confirm the regex uses a word boundary (`\b`) and that the negative-phrase guard is present.
