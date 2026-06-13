# Plan 013: Operational scripts must persist changes and report failure (stop silent no-ops / fail-open exits)

> **Executor instructions**: This plan fixes **five independent scripts**. Do each
> as its own commit; they don't depend on each other. Run every verification
> command and confirm the expected result before moving on. Honor STOP conditions.
> Update this plan's row in `plans/README.md` when done.
>
> **Drift check (run first)**: `git diff --stat b30248f..HEAD -- scripts/audit_sources.py scripts/audit_pipeline.py scripts/mark_published.py scripts/validate_export.py scripts/repair_images.py`
> For each in-scope file that changed, compare the "Current state" excerpt before
> editing; on a behavioral mismatch, STOP for that file (you may still do the others).

## Status

- **Priority**: P2
- **Effort**: M (five small fixes)
- **Risk**: LOW–MED
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `b30248f`, 2026-06-12

## Why this matters

Several operational/CLI scripts **claim success while doing nothing or while failing** — the same fail-open class as the CI gates in plan 011, but in the day-to-day tools. Each erodes trust in the tooling: a printed "✅" that didn't happen, or an exit 0 that hides a failure a CI step or operator relies on.

## Commands you will need

| Purpose | Command | Expected |
|---|---|---|
| Run a script's tests (where they exist) | `.venv/bin/pytest tests/test_security_gate.py -q` etc. | pass |
| Lint | `make lint` | exit 0 (note: scripts/ excluded from `make type`) |
| Fast suite | `make test` | all pass |

Each fix below has its own targeted verify.

## Scope

**In scope:** `scripts/audit_sources.py`, `scripts/audit_pipeline.py`, `scripts/mark_published.py`, `scripts/validate_export.py`, `scripts/repair_images.py`, and any test files you add under `tests/`.

**Out of scope:** `security_gate.py`/`quality_gate.py` (plan 011); `news_collector/` package code (the scripts should call it, not duplicate it, but refactoring duplication is a separate plan); changing the export *contract*.

## Git workflow

- Branch: `advisor/013-scripts-report-failure`
- One commit per script fix; `fix(scripts): …` style.
- Do NOT push or open a PR.

---

## Fix 1 — `audit_sources.py`: `blacklist` never writes to disk

### Current state
```python
# scripts/audit_sources.py:108-141  cmd_blacklist
def cmd_blacklist(args):
    ...
    from news_collector.config.sources import ALL_SOURCES as sources_dict, save_sources
    sources_dict[source_id]["blacklisted"] = True
    sources_dict[source_id]["blacklist_reason"] = reason
    sources_dict[source_id]["blacklisted_date"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    print(f"✅ Blacklisted '{source_id}': {reason}")   # <-- prints success
    return 0                                            # <-- but never called save_sources(...)
```
`save_sources` is imported but never called. Contrast `cmd_unblacklist` (line ~172) which **does** call `save_sources(sources_dict)`. So `blacklist <id>` is a silent no-op — the source is restored on next load.

### Step
Add `save_sources(sources_dict)` immediately before the `print("✅ Blacklisted ...")` (so the success message only prints after a successful write). Mirror `cmd_unblacklist`'s ordering.

**Verify:** `grep -n "save_sources" scripts/audit_sources.py` shows a call inside `cmd_blacklist` (not just the import). If a test harness exists for sources, run it; otherwise smoke-test in a throwaway way that does **not** commit a real `sources.yaml` change (e.g., point at a temp copy) — STOP rather than mutate the committed `sources.yaml`.

---

## Fix 2 — `mark_published.py`: `main()` always returns 0

### Current state
```python
# scripts/mark_published.py:~120-153
for path in post_paths:
    try: text = path.read_text(...)
    except OSError as exc: print(...); skipped += 1; continue
    source_url = _extract_source_url(text)
    if not source_url: print(...); skipped += 1; continue
    ...
    if db_manager.mark_article_published(source_url, ...): updated += 1
    else: skipped += 1
print(f"✅ Publicaciones actualizadas: {updated}")
if skipped: print(f"⚠️  Publicaciones omitidas: {skipped}")
return 0      # <-- unconditional
```
A run that found posts but marked none (every `mark_article_published` returned `False`, or every read failed) still exits 0.

### Step
Return non-zero when posts were found but **none** were updated and at least one was skipped due to a real failure. Keep dry-run returning 0. Suggested:
```python
if not args.dry_run and post_paths and updated == 0 and skipped > 0:
    print("❌ No se marcó ninguna publicación pese a encontrar posts.")
    return 1
return 0
```
(Do not treat legitimately-empty `post_paths` as failure unless the intent is that posts must exist — if unsure, only fail on the "found posts, updated none, had skips" condition above.)

**Verify:** add `tests/scripts/test_mark_published.py` (create the dir/`__init__` if needed) that monkeypatches `db_manager.mark_article_published` to return `False` and a fake posts dir with one post → assert `main(...)` returns `1`; and a happy path → returns `0`. `.venv/bin/pytest tests/scripts/test_mark_published.py -q` → pass.

---

## Fix 3 — `validate_export.py`: empty export passes (fail-open CI gate)

### Current state
```python
# scripts/validate_export.py:99-104
if not articles:
    print("⚠️ Warning: No articles found in export to validate.")
    # If dry-run produced 0 articles, it's technically a pass on schema ...
    # flexible for now.
    return True            # <-- empty export validates as OK
```
This script is a **CI gate**: `.github/workflows/e2e.yml:35` runs `validate_export.py output.json`. An empty/zero-article export passes, so the e2e contract check can't catch "the pipeline produced nothing."

### Step
Default to failing on empty, with an explicit opt-out for legitimate dry-runs. Add an `--allow-empty` flag (argparse) and:
```python
if not articles:
    if getattr(args, "allow_empty", False):
        print("⚠️ No articles found; --allow-empty set, passing.")
        return True
    print("❌ No articles found in export; failing validation.")
    return False
```
Wire the boolean return to a non-zero process exit (confirm `main()` does `sys.exit(0 if ok else 1)`; if it returns a bool to the caller, make the caller exit non-zero).

**Verify:** `.venv/bin/python scripts/validate_export.py <a json file with {"articles": []}>; echo $?` → non-zero; with `--allow-empty` → 0. Add `tests/scripts/test_validate_export.py` covering both. Note in your report that **CI (`e2e.yml:35`) may need `--allow-empty` if that step legitimately runs in dry-run mode** — do NOT edit the workflow yourself; flag it (STOP-adjacent).

---

## Fix 4 — `audit_pipeline.py`: `cmd_all` ignores sub-phase exit codes

### Current state
```python
# scripts/audit_pipeline.py:100-119
exit_code = 0
if cmd_sweep(sweep_args) != 0:
    print("⚠️  Sweep completed with failures ..."); exit_code = 1
cmd_blacklist_report(args)   # <-- return ignored
cmd_report(args)             # <-- return ignored
return exit_code
```

### Step
Capture and aggregate the return codes:
```python
exit_code = max(exit_code, cmd_blacklist_report(args) or 0, cmd_report(args) or 0)
```
(Use `or 0` only if those functions may return `None`; check their signatures — if they always return int, drop it.)

**Verify:** `grep -n "cmd_blacklist_report\|cmd_report" scripts/audit_pipeline.py` shows the returns being captured into `exit_code`. `make lint` clean.

---

## Fix 5 — `repair_images.py`: `has_valid_image` crashes on non-string `image`

### Current state
```python
# scripts/repair_images.py:79-92
def has_valid_image(fm):
    image = fm.get("image")
    if not image:
        return False
    if isinstance(image, str):
        if not image.strip():
            return False
        if image.startswith("http"):
            return False
    # ↓↓↓ these run even when image is NOT a str (e.g. a YAML list/dict) → AttributeError
    if image.startswith("~/assets/images/"):
        ...
    if image.startswith("/"):
        ...
    return False
```
A non-empty, non-string `image` (YAML array/mapping) passes the `if not image` guard and reaches `image.startswith(...)` at line ~92, raising `AttributeError`. The per-file loop's broad `except` swallows it and counts it failed, but the script still exits 0.

### Step
Add an early non-string guard so all `startswith` checks only run on strings:
```python
if not isinstance(image, str):
    return False        # unknown/unsupported image shape → needs attention, treat as invalid
image = image.strip()
if not image or image.startswith("http"):
    return False
```
Then the existing `~/assets/images/` and `/` checks follow, all guaranteed string. (Keep behavior identical for the normal string cases.)

**Verify:** add `tests/scripts/test_repair_images.py` with `has_valid_image({"image": ["a", "b"]})` → returns `False` (no exception); `has_valid_image({"image": "http://x/y.jpg"})` → `False`; `has_valid_image({"image": ""})` → `False`. `.venv/bin/pytest tests/scripts/test_repair_images.py -q` → pass.

---

## Done criteria

ALL must hold:

- [ ] `cmd_blacklist` calls `save_sources(...)`; `grep` confirms the call inside the function
- [ ] `mark_published.main()` returns non-zero for "found posts, updated none, had skips"; test proves it
- [ ] `validate_export` fails (non-zero) on empty export unless `--allow-empty`; test proves both
- [ ] `audit_pipeline.cmd_all` aggregates the sub-phase return codes
- [ ] `has_valid_image` returns `False` (no exception) for non-string `image`; test proves it
- [ ] New tests under `tests/scripts/` pass; `make test` exits 0; `make lint` exits 0
- [ ] Only the five scripts + new test files modified (`git status`)
- [ ] `plans/README.md` status row updated; note in your report if `e2e.yml` needs `--allow-empty`

## STOP conditions

Stop and report (for the affected fix; others can proceed) if:

- A fix would require mutating the committed `sources.yaml` / real fixtures to verify — use a temp copy or rely on the unit test instead.
- `validate_export`'s `main()` doesn't translate the bool return into a process exit code and the wiring is unclear — report it.
- An existing test encodes the current fail-open behavior (asserts pass-on-empty / return 0) — flag it; it should change with the fix.

## Maintenance notes

- A reviewer should confirm each "success" message now prints only after the work actually succeeded, and that dry-run paths still exit 0.
- Related (deferred to other plans): frontmatter parsing is duplicated across `mark_published.py`, `repair_images.py`, and `audit_published_categories.py` — consolidation is a separate tech-debt item, not done here.
