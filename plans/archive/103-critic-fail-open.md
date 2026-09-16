# Plan 103: Fail open the editorial critic on keyless verdicts + guard headline input

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat e77a039..HEAD -- news_collector/components/editorial/ai_editor.py tests/unit/editorial/`
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

On 2026-09-16 article 1181 (Galápagos corals, valid 9890-char source) was
blocked from publishing by a fiction: the editorial-critic LLM returned
non-JSON prose in 0.55s, the extractor fell back to `{}`, and the code read
that as a 0-score quality REJECT — minutes after the same content PASSED the
critic with Score 100. The bogus "hook_score 0/10" feedback sent good content
into a repair that emptied it; the empty text then burned 2 more headline LLM
calls (model refused in Spanish: "*por favor, proporciona el texto
completo…*") before the correct terminal `editorial_placeholder_blocked`.
Total waste: ~3.5 min of LLM calls plus a lost article. After this plan, a
keyless critic verdict is treated as what it is — an infra/parse failure that
fails open — and headline generation never spends LLM calls on blank input.

## Current state

The relevant files, each with one line on its role:

- `news_collector/components/editorial/ai_editor.py` — `_critic_editorial_pass` (lines 1115-1231), `_extract_editorial_critic_json` (1233-1261), `_extract_json` (965-976), `_generate_headlines` (1706-1793)

Excerpts of the code as it exists today (all read directly):

`ai_editor.py:1132-1136` — the documented contract:

```python
Fails open: if the prompt is unavailable, the model returns
unparseable output, or the call raises, the article is approved so
the editorial critic never becomes a publication blocker for
infrastructure reasons. Quality regressions surface via the auditor.
```

`ai_editor.py:1164-1174` — fail-open only on raise:

```python
try:
    response = self._send_prompt(
        user_prompt, system=system_prompt, model=self.editor_model
    )
    logger.debug(f"Editorial Critic raw response: {response[:300]}")
    result = self._extract_editorial_critic_json(response)
except Exception as e:
    logger.warning(
        f"Editorial Critic Pass Failed (infra error): {e} - failing open"
    )
    return True, None, True
```

`ai_editor.py:1176-1197` — keyless `{}` flows into zeros (THE BUG):

```python
try:
    approved = bool(result.get("approved", False))
    ...
    average = float(result.get("average", 0.0))
    scores = {key: int(result.get(key, 0)) for key in (...7 dims...)}
except (TypeError, ValueError) as e:
    ...return True, None, True   # only reached on coercion failure, not on {}
```

`ai_editor.py:965-976` — why no raise happens on prose without braces:

```python
result = self.provider._extract_json(text)
if not result and "{" in text:
    raise ValueError("No parsing valid JSON object found")
return cast(dict[Any, Any], result)   # prose without "{" → returns {} silently
```

`ai_editor.py:1233-1261` — the fallback chain ending in the silent `{}`:
regex scan for `approved`/`average` → `_extract_critic_json` (`score`) →
`self._extract_json(text)` (may return `{}`).

`ai_editor.py:1706-1744` — headline prompt embeds `adapted_content[:2000]`
with no blank check; on exhaustion returns `{}` for deterministic repair
(`:1787-1793`, plan 063 — keep that behavior).

The 1181 log signature (for your regression replay):
`_critic_pass Score 100` → 0.55s critic call → "no JSON with
'approved'/'average' found, falling back to generic extractor" →
`EDITORIAL CRITIC REJECTED (avg=0.0, all 0)` → repair feedback "Bajo puntaje
en hook_score (0/10)…" (auto-built at `:1212-1218`, proving the zeros came
from missing keys, not a judgment).

Repo conventions that apply here:

- The headline critic already fails open on infra error (`:1326-1329`) — copy that pattern, don't invent one.
- Repair-loop and deterministic-repair semantics stay untouched; this plan only changes verdict interpretation + headline input guard.

## Commands you will need

| Purpose   | Command                  | Provenance | Expected on success |
|-----------|--------------------------|------------|---------------------|
| Install   | `make bootstrap`         | declared   | exit 0 |
| Lint      | `make lint`              | declared   | exit 0 |
| Type      | `make type`              | declared   | exit 0, ratchet passes |
| Tests     | `make test`              | declared   | all pass |

## Scope

**In scope** (the only files you should modify):

- `news_collector/components/editorial/ai_editor.py` (critic verdict check + headline blank guard only)
- `tests/unit/editorial/` (new/updated tests; check the dir layout first — existing critic tests live near `test_ai_editor_coverage.py`)

**Out of scope** (do NOT touch, even though they look related):

- Repair-loop bounds, retry counts, critic prompts, thresholds — quality policy is not under review.
- The terminal `editorial_placeholder_blocked` check (`:387-420`) — correctly fail-closed, keep it.
- Provider-level `_extract_json` (NVIDIA/ollama providers) — the fix belongs at the verdict layer, not the parser.

## Git workflow

- Branch: `advisor/103-critic-fail-open`
- Conventional commits, e.g. `fix(editorial): fail open on keyless critic verdicts`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 0: Establish a green baseline

Run `Install`, then `Lint`, `Type`, `Tests` on the unmodified checkout. On any
`declared`-command failure on the clean tree (modulo the known flaky
`test_429_retry_after_handling`, which passes in isolation): **STOP and report**
with exact output.

**Verify**: all commands match their expected results on the unmodified checkout.

### Step 1: Fail open on keyless critic verdicts

In `_critic_editorial_pass`, immediately after `result = self._extract_editorial_critic_json(response)` succeeds (i.e. inside the `try`, before the score-coercion `try`), insert:

```python
if "approved" not in result and "average" not in result:
    logger.warning(
        "Editorial Critic returned no verdict keys "
        f"('approved'/'average' missing; keys present: {sorted(map(str, result.keys()))}) — "
        "treating as infra/parse failure, failing open."
    )
    return True, None, True
```

- Do NOT log the full response (it can be kilobytes of prose); keys list only.
- Everything downstream (approved path, feedback builder, REJECT log) stays identical.

**Verify**: `make lint` → exit 0.

### Step 2: Guard headline generation against blank input

At the top of `_generate_headlines`, before building `base_prompt`:

```python
if not _extract_publishable_body(adapted_content or ""):
    logger.warning(
        "Headline generation skipped: no publishable body in adapted "
        "content; relying on deterministic repair."
    )
    return {}
```

(`{}` is what exhaustion already returns — downstream handling identical, zero LLM calls burned.)

**Verify**: `make lint` → exit 0.

### Step 3: Add regression tests

In `tests/unit/editorial/` (follow the existing stubbed-`_send_prompt` pattern from `test_ai_editor_coverage.py`):

1. Critic returns prose without JSON/keys → `_critic_editorial_pass` returns `(True, None, True)` (pins the fail-open; would have returned REJECT before the fix — verify by asserting `is_valid is True`).
2. Critic returns a real `{"approved": false, ...scores...}` verdict → still `(False, feedback, recoverable)` (pins genuine rejections unaffected).
3. `_generate_headlines("")` and whitespace/frontmatter-only input → `{}` with `_send_prompt` never called (assert via spy/mock call count).
4. 1181-shape replay: critic-passed content + keyless editorial-critic response → article NOT sent to repair on zero scores (assert `_repair_editorial` not called, or assert process-level outcome per whatever seam the existing tests use — read them first).

**Verify**: new tests pass; full editorial test dir green.

### Step 4: Run the full gates

**Verify**: `make lint && make type && make test` → all exit 0 (modulo the known flake signature only).

## Test plan

- New: keyless-verdict approval, genuine-rejection preservation, blank-headline-input short-circuit, 1181 replay.
- Existing `test_ai_editor_coverage.py` + critic suites green (no verdict semantics change for well-formed responses).

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `make lint`, `make type`, `make test` all exit 0 (modulo known flake only)
- [ ] Keyless critic dict can no longer produce a REJECT (grep the REJECT path: it is reachable only when `approved` or `average` present — reviewer confirms)
- [ ] New tests exist and pass (≥4)
- [ ] `git diff --name-only e77a039...HEAD` lists only the in-scope files (plus already-merged wave files, expected)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- The code at the locations in "Current state" doesn't match the excerpts.
- A legitimate critic schema exists WITHOUT `approved`/`average` (check `prompts.yaml::editor_critic` required fields first — if the schema genuinely omits both, the key check is wrong; report).
- `_send_prompt` is unmockable in the test seams you need (report the seam gap instead of weakening the tests).
- A step's verification fails twice after a reasonable fix attempt.

## Maintenance notes

- If the critic schema ever legitimately drops both keys, this check must be updated in lockstep — link the schema location in a code comment.
- The repair loop can still empty content on GENUINE rejections; a fail-fast after empty repair is a separate, deferred decision (needs care: repair-then-retry is sometimes productive).
- Reviewers: confirm the warning (not the response body) is what gets logged.
- **Deferred:** fail-fast when `_repair_editorial` returns empty — unblocked, needs a productive-vs-doomed-repair study first.
