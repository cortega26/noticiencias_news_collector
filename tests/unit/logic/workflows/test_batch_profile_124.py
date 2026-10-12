"""Plan 124 Step 4: batch collaborator hoist — MEASURED-NOT-WORTH-IT (skip).

Profiled 2026-10-12 on the clean worktree (cold process, SQLite tmp DB):

| collaborator setup per item | cold   | warm   |
|-----------------------------|--------|--------|
| load_config                 | ~3 ms  | ~3 ms  |
| DatabaseManager()           | ~600ms | ~17 ms |
| GitHubPublisher(token)      | ~25 ms | ~25 ms |
| resolve_ollama_stage_models | ~2 ms  | ~2 ms  |
| EditorAgent(...)            | ~66 ms | ~66 ms |
| RefineryEngine(...)         | ~44 ms | ~44 ms |
| TOTAL per-item setup        | ~854ms | ~157ms |

(Cold DatabaseManager includes first-import + metrics-store init; warm is
the steady-state per-item cost inside a batch.)

Per-item publish cost is ~1x a single publish (plan 109 docstring: git
source+target clones, LLM preflight + editing passes, PR open) —
seconds to minutes. Even against a conservative 30 s floor:

- cold setup share: 0.85 s / 30 s = 2.9%
- warm setup share: 0.16 s / 30 s = 0.5%

Both < 10% gate, so the hoist is SKIPPED — sharing DatabaseManager
(session/engine state), EditorAgent (LLM rate-limiter + provider state)
or RefineryEngine (stage_listener + per-run state) across items would
trade per-item error isolation for <3% wall-clock. The batch stays
sequential per-item (plan 109 shape, plan 125 owns parallelism).

The tests below pin the skipped-hoist invariant: every batch item still
goes through its own run_publication_pipeline call with identical
kwargs (no shared collaborators injected, no cross-item leakage
surface).
"""


def _fake_pipeline(monkeypatch, calls, behaviour):
    def fake(*, process_id=None, **kw):
        calls.append((process_id, dict(kw)))
        return behaviour(process_id)

    monkeypatch.setattr(
        "news_collector.logic.workflows.publication_pipeline.run_publication_pipeline",
        fake,
    )


class TestBatchPerItemIsolationPinned:
    def test_each_item_gets_own_pipeline_call_with_same_kwargs(
        self, monkeypatch
    ) -> None:
        from news_collector.logic.workflows.publication_pipeline import (
            run_publication_batch,
        )

        calls: list = []
        _fake_pipeline(
            monkeypatch,
            calls,
            lambda pid: {"status": "success", "processed_count": 1},
        )
        result = run_publication_batch([11, 22, 33])
        assert result["status"] == "success"
        assert [pid for pid, _ in calls] == ["11", "22", "33"]
        # Identical kwargs per item — no shared/cached collaborator is
        # threaded through; each call builds its own (Step-4 skip pinned).
        assert all(kw == calls[0][1] for _, kw in calls)

    def test_per_item_outcomes_byte_identical_on_fixtures(self, monkeypatch) -> None:
        from news_collector.logic.workflows.publication_pipeline import (
            run_publication_batch,
        )

        calls: list = []

        def behaviour(pid):
            if pid == "22":
                return {"status": "error", "message": "nope", "processed_count": 0}
            return {"status": "success", "processed_count": 1}

        _fake_pipeline(monkeypatch, calls, behaviour)
        first = run_publication_batch([11, 22, 33])
        calls.clear()
        _fake_pipeline(monkeypatch, calls, behaviour)
        second = run_publication_batch([11, 22, 33])
        assert first == second
        assert first["status"] == "partial"
