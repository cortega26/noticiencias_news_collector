# Plan 101: Inject config explicitly — remove `load_config()` from policy constructors and the collector validator

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat e77a039..HEAD -- news_collector/editorial/council.py news_collector/editorial/classifier.py news_collector/scoring/pre_scorer.py news_collector/contracts/collector.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P3
- **Effort**: M
- **Risk**: MED
- **Depends on**: none
- **Category**: tech-debt
- **Planned at**: commit `e77a039`, 2026-09-16

## Why this matters

Four policy modules and one contract validator call `load_config()` /
`get_runtime_config()` deep inside constructors and per-article validation
(LAW-B4: env lookups belong at bootstrap). Consequences today: policy units
can't run without ambient config/env, tests must mock half the system to verify
one rule, and contract validation outcomes silently depend on mutable global
runtime config. After this plan, collaborators are explicit constructor args
and the validator's language set is injected — policy becomes unit-testable in
isolation.

## Current state

The relevant files, each with one line on its role:

- `news_collector/editorial/council.py` — `EditorialCouncil.__init__` (lines 53-63)
- `news_collector/editorial/classifier.py` — `EditorialClassifier.__init__` (lines ~25-35, same shape)
- `news_collector/scoring/pre_scorer.py` — `PreScorer.__init__` (lines 36-49)
- `news_collector/contracts/collector.py` — `_supported_languages()` live-read (lines 24-30) used by the `language` validator

Excerpts (verified by direct read):

`council.py:53-63` (classifier and pre_scorer share the shape, stage name differs):

```python
def __init__(self, llm_client: Optional[Any] = None, config: Any | None = None):
    if llm_client is None:
        active_config = config or load_config()
        model = get_model_for_stage("council", config=active_config, logger=logger)
        self.llm = get_provider(
            config=active_config,
            api_url=active_config.ollama.api_url,
            model=model,
        )
    else:
        self.llm = llm_client
```

`contracts/collector.py:24-30`:

```python
def _supported_languages() -> set[str]:
    """Read live so a refresh_runtime_config() change takes effect immediately."""
    return set(
        get_runtime_config().text_processing_config.get(
            "supported_languages", ["en", "es"]
        )
    )
```

Note the validator docstring documents INTENT (live refresh). The fix must preserve refresh semantics (see Step 2) — this is the subtle part of the plan.

Repo conventions that apply here:

- LAW-B3 heuristics: "prefer explicit collaborators over hidden globals".
- LAW-B4 exception: none applies — these are policy/contract modules, not edge I/O. (The `cognitive_scorer` I/O exception is recorded by-design and NOT in scope.)
- Caller updates must stay mechanical; constructor signature changes are the blast radius to measure first.

NOT in scope (do not re-audit): `scoring/cognitive_scorer.py` — recorded by-design in `docs/audits/2026-08-plans-rejected-findings.md`.

## Commands you will need

| Purpose   | Command                  | Provenance | Expected on success |
|-----------|--------------------------|------------|---------------------|
| Install   | `make bootstrap`         | declared   | exit 0 |
| Lint      | `make lint`              | declared   | exit 0 |
| Type      | `make type`              | declared   | exit 0, ratchet passes |
| Tests     | `make test`              | declared   | all pass |
| Boundaries| `make test-boundaries`   | declared   | all pass |
| Contracts | `make test-contracts`    | declared   | all pass (contract touched) |

## Scope

**In scope** (the only files you should modify):

- `news_collector/editorial/council.py`, `news_collector/editorial/classifier.py`, `news_collector/scoring/pre_scorer.py` (constructors)
- `news_collector/contracts/collector.py` (language-set injection only)
- Their direct callers (constructor call sites — mechanical updates only)
- Tests for the three policy classes + collector contract language validation

**Out of scope** (do NOT touch, even though they look related):

- `components/editorial/auditor.py` (`load_config` fallbacks there too) — same disease, NOT verified for this plan; report, don't expand.
- `cognitive_scorer.py` — by-design exception.
- `get_model_for_stage` / `get_provider` internals — collaborators' construction stays as-is; only the *call* moves to explicit args.
- Serving per-request `load_config()` calls (unvetted investigate item) — separate.

## Git workflow

- Branch: `advisor/101-explicit-config-injection`
- Conventional commits, e.g. `refactor(policy): inject config explicitly into policy constructors`.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 0: Establish a green baseline

Run `Install`, then `Lint`, `Type`, `Tests` on the unmodified checkout. On any
`declared`-command failure on the clean tree: **STOP and report** with exact output.

**Verify**: all commands match their expected results on the unmodified checkout.

### Step 1: Measure the blast radius (no edits yet)

1. `grep -rn "EditorialCouncil(\|EditorialClassifier(\|PreScorer(" news_collector/ apps/ scripts/ tools/ tests/ | grep -v __pycache__` — every construction site.
2. `grep -rn "_supported_languages\|supported_languages" news_collector/ | grep -v __pycache__` — every consumer of the language set.
3. Count distinct production call sites. If MORE THAN ~10 production files construct these classes without passing config today, STOP and report the list — the migration needs staging (this plan assumes a small, mechanical fan-out).

**Verify**: written call-site inventory with counts. Proceed only if the fan-out is small and mechanical.

### Step 2: Make config/llm_client explicit (backward-compatible signatures)

For each of the three classes, change:

```python
def __init__(self, llm_client: Optional[Any] = None, config: Any | None = None):
    if llm_client is None:
        active_config = config or load_config()
```

to require one of the two explicitly — recommended shape (keeps all current
explicit callers working):

```python
def __init__(self, llm_client: Optional[Any] = None, config: Any | None = None):
    if llm_client is None and config is None:
        raise ValueError("<Class> requires llm_client or config explicitly; ...")
    if llm_client is None:
        active_config = config  # no load_config() fallback
        ...
```

i.e. delete the `or load_config()` fallback, keep the rest identical. Update
every production call site found in Step 1 to pass what it already has (most
callers hold a config — pass it; where a caller has neither, wire it from its
own bootstrap context, never from a new `load_config()` one level up).

For `contracts/collector.py`: replace the live `get_runtime_config()` read with
an explicitly set module-level snapshot:

```python
_SUPPORTED_LANGUAGES: set[str] | None = None

def set_supported_languages(langs) -> None: ...
def _supported_languages() -> set[str]:
    if _SUPPORTED_LANGUAGES is None:
        # bootstrap default, identical to today's fallback
        return {"en", "es"}
    return set(_SUPPORTED_LANGUAGES)
```

and call `set_supported_languages(...)` from the bootstrap path that calls
`refresh_runtime_config()` (find it — grep `refresh_runtime_config` callers;
there should be one bootstrap owner). This preserves the documented
refresh-takes-effect-immediately semantics through an explicit channel instead
of ambient global reads per article. If no single bootstrap owner exists, STOP
and report (the live-read is load-bearing architecture, not a slip).

**Verify**: `grep -rn "or load_config()" news_collector/editorial/council.py news_collector/editorial/classifier.py news_collector/scoring/pre_scorer.py` → no matches; `make lint` → exit 0.

### Step 3: Tests

1. For each class: construct with a fake `llm_client` and NO config/env — must work with zero ambient state (this is the test that fails today). Assert no `load_config` call (monkeypatch it to raise).
2. Constructing with neither arg raises `ValueError` (pins the new explicitness).
3. Collector contract: set snapshot via setter → validator honors it; unset → `{"en", "es"}` default; refresh path updates it (test the bootstrap wiring once).
4. Update existing tests that relied on the implicit fallback (they should now pass config explicitly — mechanical).

**Verify**: `.venv/bin/python -m pytest tests/unit/editorial tests/unit/scoring tests/unit/contracts -q` → all pass including new tests. (Check those dirs exist first; adapt paths to the actual layout.)

### Step 4: Run the full gates

**Verify**: `make lint && make type && make test && make test-boundaries && make test-contracts` → all exit 0.

## Test plan

- New isolation tests (fake client, no env, `load_config` rigged to raise) for all three classes.
- New setter/refresh tests for the language snapshot.
- Full contract + boundary suites green (constructor signatures are cross-boundary).

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `make lint`, `make type`, `make test`, `make test-boundaries`, `make test-contracts` all exit 0
- [ ] No `load_config()` call remains in the three constructors (grep)
- [ ] No `get_runtime_config()` call remains in `contracts/collector.py` (grep)
- [ ] Isolation tests (no-env construction) exist and pass
- [ ] `git diff --name-only e77a039...HEAD` lists only the in-scope files (+ mechanical caller updates — list them in the report)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- The code at the locations in "Current state" doesn't match the excerpts.
- Step 1 fan-out exceeds ~10 production files, or any caller cannot supply config without its own `load_config()` (that just moves the violation — report the chain).
- No single bootstrap owner exists for the language-snapshot setter.
- `auditor.py` or other modules' fallbacks entangle with these constructors (report, don't expand scope).
- A step's verification fails twice after a reasonable fix attempt.

## Maintenance notes

- New policy classes must take collaborators as constructor args from day one — no `load_config()` fallbacks, ever. Consider adding that line to `docs/AGENTS.md` §8 heuristics in a follow-up docs pass.
- Reviewers: every updated call site should pass an object it already held; any site that newly calls `load_config()` to satisfy the signature has missed the point — reject.
- **Deferred:** `auditor.py` fallbacks, serving per-request `load_config()` — same theme, separate verification each.
