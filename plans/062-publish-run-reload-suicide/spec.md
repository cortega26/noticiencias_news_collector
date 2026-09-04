# Plan 062 — Publish run dies: uvicorn --reload restarts on the run's own clones

## Symptom

Clicking `✨ Refine & publish` returns `202 Accepted` and the Refinery run
starts (run 15), but ~6s later the API process restarts and the run is
recovered as an expired lease (`Recovered 1 expired publication-run
lease(s) ... [15]`). The GUI reports `interrupted (server restarted
mid-run)`. A full Refine-&-Publish can therefore never finish under
`make serve` / `make admin`.

## Root cause

`news_collector/serving/__main__.py` runs `uvicorn.run(..., reload=True)`
with the default watch root (repo root) and no excludes. Every publication
run clones two whole repos under `temp/` (`temp/source` =
noticiencias_news_collector, `temp/target` = noticiencias) → hundreds of
`.py` changes → `WatchFiles detected changes in 'temp/source/...'` →
full server restart → the in-process background run is killed.

Evidence: user log 19:56:36 run start → 19:56:41/42 clone into
`temp/source` → `WatchFiles detected changes` → `Shutting down` →
`Started server process` + `recovered 1 stale publication run(s): [15]`.

## Fix

`news_collector/serving/__main__.py`: pin `reload_dirs` to the package
that actually serves (`news_collector/`, repo root for config?) and add
`reload_excludes` for runtime-write directories (`temp/*`, `data/*`,
`logs/*`). Minimal form:

```python
uvicorn.run(
    "news_collector.serving.__main__:app",
    host="0.0.0.0",
    port=8000,
    reload=True,
    reload_excludes=["temp/*", "data/*", "logs/*"],
)
```

Notes:
- Both `make serve` and `make admin` launch via this `__main__`, so one
  change covers both.
- `temp/`, `data/`, `logs/` all exist at repo root and are written at
  runtime (clones, sqlite, exports, metrics). No source `.py` that should
  trigger reload lives there (`scripts/` stays watched).
- Out of scope: making publication runs survive restarts (durable resume),
  and the wasteful full-repo clone into `temp/source` instead of reusing
  the working copy — both noted as follow-ups.

## Verification

1. Isolated reload test on a scratch port (do NOT disturb the user's
   `:8000` stack): start `uvicorn ... :8100 --reload` equivalent via the
   edited `__main__` parametrized? `__main__` hardcodes port 8000, so the
   test runs a tiny inline uvicorn app importing the same
   `reload_excludes` list... Better: extract the excludes into a
   module-level constant `RELOAD_EXCLUDES` in `__main__.py` and assert in
   a unit test that it covers `temp/`, `data/`, `logs/`, plus a live test:
   run uvicorn with those excludes on port 8100, `touch temp/probe.py`
   → no restart; `touch news_collector/serving/probe_tmp.py` → restart;
   remove probe files afterwards.
2. `make lint` on the touched file;contract/boundary gates unaffected
   (no contract change) — run the fast serving-admin subset to be safe.
3. User action required: restart `make admin` (the running API still has
   the old watcher) and click publish again; a real run takes minutes
   (editor → auditor → image → PR), not seconds.
