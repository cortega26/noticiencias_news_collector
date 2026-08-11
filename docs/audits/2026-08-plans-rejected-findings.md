# Findings Considered and Rejected by the Plans Audit Passes

> **Pointer.** This file holds the audit-journal content formerly embedded in
> `plans/README.md` (split out 2026-08-11 so the ledger stays thin). It is the
> authoritative record of "do not re-audit" decisions. Revisit only if the
> underlying evidence changes.

## Third pass (2026-08-07, backend correctness/regression sweep) — rejected after vetting

- **"V2 article missing required enrichment fields: ['sources']" ERROR in today's log** (`ai_editor.py:2079`, 1 occurrence): rejected as a defect. This is the intended fail-safe — a schema_version≥2 article missing an enrichment field blocks publish instead of shipping incomplete content. The single occurrence is consistent with being a downstream symptom of the same NVIDIA flakiness plan 051/053 target, not a separate bug.
- **Recency-gate linear-tail branch ordering for `candidate_max_age_days < 7`** (`basic_scorer.py:336-347`, plan 050, already merged): the `elif age_hours <= 168` branch is checked before the `elif age_hours < max_age_hours` branch, so a hypothetical config with `candidate_max_age_days` under 7 days would compute a nonzero recency score for candidates technically past the cutoff. Not reachable in practice — `article_repository.get_articles_by_score`'s DB-level `max_age_days` filter already excludes such candidates before scoring runs, and the default is 30 days. Only relevant to a future misconfiguration; not worth a plan on its own.
- **`collector.source.soft_timeout_exceeded`** (24 occurrences in today's real run — the largest non-NVIDIA WARNING category): checked across rotated `.gz` logs from 2026-06-14 through today, isolating the real collector process by activity span (not line count, which favors short-lived pytest workers). The event appears both before (2026-08-02: 36, 2026-06-14: 8) and after (2026-08-06: 2, 2026-08-07: 24) commit `c745763` ("bound async source fan-out with semaphore", 2026-08-04) — it correlates with total run duration, itself driven by NVIDIA timeouts, not with that commit. Not a regression from it.
- **"asyncio.run() crashes the collection pipeline"** (`collectors/dispatcher.py:122`): rejected. `system/__init__.py:330` guards with `if hasattr(... "collect_from_multiple_sources_async")` and `await`s the async path; the sync `asyncio.run` wrapper is a fallback for collectors lacking the async method, and the Dispatcher has it — no crash.
- **"PreScorer is dead/orphaned code from the pre-score removal commit"**: rejected. Commit `c8ccfa5` removed *source-based* pre-scoring, not the `PreScorer` class, which is live (`collectors/rss_collector.py:36,86,827`).
- **"validation/rules.py has zero test coverage"**: downgraded/rejected. Validation is covered by `tests/unit/validation/`, `tests/test_quality_rules.py`, and `tests/test_validation_coordinator.py`.
- **Low-value security items** (GitHub PR-title HTML-escaping, unauth health probes, image content-type sniffing, feedparser bozo leniency, GitHub-URL string split): noted but not planned — defensive-only, low impact, or handled safely by the platform (GitHub API treats title/body as plain text).
- **`cognitive_scorer.py` imports infra + sqlite3 (layering violation)**: noted, not planned as a refactor. An LLM-backed scorer inherently does I/O, so the "scoring runs without network/DB" rule likely has an intended exception here; a DI refactor would fight a deliberate design. Revisit only as a spike if desired.

## Second pass (apps/refinery, scripts, tools) — rejected after vetting

- **Refinery image download SSRF** (`image_handler.py`): rejected. The downloader uses `RobustRequestsClient`, whose `SSRFSafeSession.get_adapter` calls `validate_url_safety` on every request (`infrastructure/requests_client.py:94-115,129`).
- **Refinery `unsafe_allow_html` XSS from article data**: rejected. The 5 `unsafe_allow_html=True` sites in `admin_panel.py` render only app/config/GitHub values (floats, policy thresholds, db paths, branch/SHA); untrusted article text is shown via default-escaped `st.write`.
- **`DELETE FROM {table}` SQL injection** (`admin_panel.py:1770`, `verify_fix.py:30`): rejected (×2). Table names come from a hardcoded list; already `# noqa/nosec`.
- **Refinery GitHub-`conclusion` HTML injection**: rejected. `conclusion` is a GitHub-controlled workflow enum, not attacker text.
- **Manual-URL-ingestion SSRF** (`admin_panel.py:2043`): rejected. `manual_ingest.py` uses `validate_url_safety` and the action is auth-gated.
- **gitleaks allowlist silent regex skip** (`security_gate.py:238`): rejected — fails *safe* (a broken allowlist entry over-blocks, never under-reports secrets).

## Second pass — noted, not planned

- **`admin_panel.py` is a 2951-LOC god module** (31 broad `except Exception`, two silent `pass` swallows at lines ~1730/2612): real tech debt, but no acute bug and L-effort to split; not worth a plan now.
- **`scripts/` + `tools/` (~12K LOC) excluded from mypy** (`pyproject.toml:117`): a genuine type blind spot, but bringing 85 scripts under strict mypy is an L-effort roadmap item that would surface a large backlog — defer; tackle as a staged initiative, not a one-shot plan.

## Third pass (deep re-run, 2026-06-13) — rejected after vetting

- **`REFINERY-10` credibility-zero reset**: rejected (false positive). `float(default_data.get("credibility_score", 0.8))` returns a stored `0` correctly — the `0.8` default applies only when the key is absent. Credibility is the one source field the editor handles right.
- **`DEBT-02` "validate_export should import AstroPost"**: downgraded/rejected. `validate_export.py` checks the `news_collector.export.v1` contract (title/url/source_id/published_date/summary), **not** the `AstroPost` frontend schema.

## Third pass — noted, not planned

- **`REFINERY-04/05/06/07/08/09`** (refinery minor): low-impact UI nits — fix opportunistically when next in `admin_panel.py`, not worth dedicated plans.
- **`DEBT-01` frontmatter parsing duplicated**, **`TESTS-01/02`** state-mutating scripts lack tests, **`DX-01`** inconsistent `sys.path` bootstrap patterns, **`DEBT-04`** dead one-off scripts: deferred consolidation.
- **`DEBT-03`** `admin_panel.py` tangles ~6 responsibilities: defer until refinery has characterization tests.
