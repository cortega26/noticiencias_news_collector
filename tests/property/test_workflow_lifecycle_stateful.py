"""Plan 080 / Phase 1 — model-based lifecycle regression tests.

One Hypothesis `RuleBasedStateMachine` exercises both
`CollectionRunWorkflow` and `PublicationRunWorkflow` against one isolated,
machine-owned SQLite database with a controlled clock and no-op dispatch,
checking every observation against an independently hand-computed
expected-state model. The model never calls `recover_expired_leases()` (or
inspects its SQL predicate) to decide what the expected answer should be —
`_is_stale_running` below is a from-scratch re-derivation of the same rule
from `plans/080/01-stateful-workflows.md` / the workflow modules' own
docstrings, so a real production regression in the recovery predicate has
something independent to disagree with.

Conventions copied from the existing unit tests
(`tests/unit/logic/workflows/test_collection_run_workflow.py`,
`tests/unit/logic/workflows/test_publication_run_workflow.py`) and from
Plan 078 (`plans/archive/078-startup-less-lease-recovery/spec.md`):
real SQLite via `DatabaseManager` + `Base.metadata.create_all`, `_dispatch`
monkeypatched to a no-op, `_transition` used directly as the queued->running
seam, and the "running + NULL heartbeat is only stale once started_at is
lease-old" nuance from the Plan 078 incident.

W1-W5 evidence for this file lives in `plans/080/tests/phase-1-results.md`.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import pytest
from sqlalchemy import select

hypothesis = pytest.importorskip("hypothesis")
from hypothesis import settings  # type: ignore[import-not-found]
from hypothesis import strategies as st  # type: ignore[import-not-found]
from hypothesis.stateful import (  # type: ignore[import-not-found]
    RuleBasedStateMachine,
    invariant,
    rule,
)

from news_collector.logic.workflows import collection_run_workflow as _collection_module
from news_collector.logic.workflows import (
    publication_run_workflow as _publication_module,
)
from news_collector.logic.workflows.collection_run_workflow import CollectionRunWorkflow
from news_collector.logic.workflows.publication_run_workflow import (
    PublicationRunWorkflow,
)
from news_collector.storage.database import DatabaseManager
from news_collector.storage.models import Base, WorkflowRun

LEASE_SECONDS = 60


# ---------------------------------------------------------------------------
# Controlled clock — machine-owned, patched into both workflow modules'
# `datetime` binding (each module does `from datetime import datetime`, so
# each needs its own patch target even though both point at the same clock).
# ---------------------------------------------------------------------------


class _Clock:
    """Holds a plain (non-subclassed) aware UTC ``datetime``. Handing
    SQLAlchemy a plain ``datetime`` — never a ``_FakeDateTime`` instance —
    avoids any risk of a foreign subclass reaching the bind path."""

    def __init__(self, start: datetime) -> None:
        self.now = start

    def advance(self, seconds: int) -> None:
        self.now = self.now + timedelta(seconds=seconds)


def _make_fake_datetime(clock: _Clock) -> type:
    class _FakeDateTime(datetime):
        @classmethod
        def now(cls, tz=None):  # noqa: D102 - trivial override
            return clock.now

    return _FakeDateTime


def _as_utc(value: datetime | None) -> datetime | None:
    """Normalize a timestamp read back through the ORM to a comparable
    aware-UTC form. SQLite's ``DateTime(timezone=True)`` does not preserve
    tzinfo on read, so every value comes back naive; every write in this
    file goes through the controlled UTC clock, so naive == UTC here."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _is_stale_running(record: dict[str, Any], *, cutoff: datetime) -> bool:
    """Independent re-derivation of the recovery predicate (W2): a
    ``running`` row is stale iff its heartbeat is older than ``cutoff``, or
    -- no heartbeat yet -- its ``started_at`` is older than ``cutoff``.
    Equality is fresh (strict ``<`` only). This function must never call
    or consult ``recover_expired_leases()``; it exists so the model has an
    opinion the real implementation can be checked against.
    """
    if record["status"] != "running":
        return False
    heartbeat_at = record["heartbeat_at"]
    if heartbeat_at is not None:
        return heartbeat_at < cutoff
    return record["started_at"] < cutoff


# ---------------------------------------------------------------------------
# Explicit 59/60/61-second boundary examples (W2) — deterministic, so
# discovery of the exact edge does not depend on Hypothesis's random draws.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "age_seconds, expect_recovered",
    [(59, False), (60, False), (61, True)],
)
def test_collection_expiry_boundary_is_strict(
    tmp_path, monkeypatch, age_seconds, expect_recovered
):
    """A frozen clock is required here: without it, real wall-clock time
    elapses between capturing `now` and the workflow's own internal
    `datetime.now(timezone.utc)` call, which shifts the 60s boundary by a
    few milliseconds and makes the exact-equality case flaky."""
    manager = DatabaseManager(
        {"type": "sqlite", "path": tmp_path / "boundary_collection.db"}
    )
    Base.metadata.create_all(manager.engine)
    try:
        clock = _Clock(datetime(2026, 1, 1, tzinfo=timezone.utc))
        monkeypatch.setattr(_collection_module, "datetime", _make_fake_datetime(clock))
        workflow = CollectionRunWorkflow(manager, lease_timeout_seconds=LEASE_SECONDS)
        now = clock.now
        with manager.get_session() as session:
            row = WorkflowRun(
                run_type="collection",
                status="running",
                started_at=now - timedelta(seconds=age_seconds + 3600),
                heartbeat_at=now - timedelta(seconds=age_seconds),
            )
            session.add(row)
            session.commit()
            row_id = row.id

        recovered = workflow.recover_expired_leases(include_queued=False)

        assert (row_id in recovered) is expect_recovered
    finally:
        manager.close()


@pytest.mark.parametrize(
    "age_seconds, expect_recovered",
    [(59, False), (60, False), (61, True)],
)
def test_publication_expiry_boundary_is_strict(
    tmp_path, monkeypatch, age_seconds, expect_recovered
):
    manager = DatabaseManager(
        {"type": "sqlite", "path": tmp_path / "boundary_publication.db"}
    )
    Base.metadata.create_all(manager.engine)
    try:
        clock = _Clock(datetime(2026, 1, 1, tzinfo=timezone.utc))
        monkeypatch.setattr(_publication_module, "datetime", _make_fake_datetime(clock))
        workflow = PublicationRunWorkflow(
            manager,
            lease_timeout_seconds=LEASE_SECONDS,
            publication_attempts_dir=tmp_path / "attempts",
        )
        now = clock.now
        with manager.get_session() as session:
            row = WorkflowRun(
                run_type="publication",
                status="running",
                started_at=now - timedelta(seconds=age_seconds + 3600),
                heartbeat_at=now - timedelta(seconds=age_seconds),
            )
            session.add(row)
            session.commit()
            row_id = row.id

        recovered = workflow.recover_expired_leases(include_queued=False)

        assert (row_id in recovered) is expect_recovered
    finally:
        manager.close()


@pytest.mark.parametrize(
    "age_seconds, expect_recovered",
    [(59, False), (60, False), (61, True)],
)
def test_null_heartbeat_uses_started_at_with_the_same_strict_boundary(
    tmp_path, monkeypatch, age_seconds, expect_recovered
):
    """W2: "NULL heartbeat uses the same strict comparison on started_at.\" """
    manager = DatabaseManager({"type": "sqlite", "path": tmp_path / "boundary_null.db"})
    Base.metadata.create_all(manager.engine)
    try:
        clock = _Clock(datetime(2026, 1, 1, tzinfo=timezone.utc))
        monkeypatch.setattr(_collection_module, "datetime", _make_fake_datetime(clock))
        workflow = CollectionRunWorkflow(manager, lease_timeout_seconds=LEASE_SECONDS)
        now = clock.now
        with manager.get_session() as session:
            row = WorkflowRun(
                run_type="collection",
                status="running",
                started_at=now - timedelta(seconds=age_seconds),
                heartbeat_at=None,
            )
            session.add(row)
            session.commit()
            row_id = row.id

        recovered = workflow.recover_expired_leases(include_queued=False)

        assert (row_id in recovered) is expect_recovered
    finally:
        manager.close()


# ---------------------------------------------------------------------------
# The stateful machine
# ---------------------------------------------------------------------------


class WorkflowLifecycleMachine(RuleBasedStateMachine):
    """Exercises both workflows together against one isolated,
    machine-owned SQLite database. Not a generic workflow-testing
    framework: it has exactly two concrete consumers
    (`CollectionRunWorkflow`, `PublicationRunWorkflow`) and exists to prove
    lifecycle/isolation invariants between them, per
    `plans/080/01-stateful-workflows.md`.
    """

    def __init__(self) -> None:
        super().__init__()
        self._tmpdir: TemporaryDirectory | None = None
        self._manager: DatabaseManager | None = None
        self._monkeypatch: pytest.MonkeyPatch | None = None
        try:
            self._tmpdir = TemporaryDirectory()
            root = Path(self._tmpdir.name)
            self._manager = DatabaseManager(
                {"type": "sqlite", "path": root / "lifecycle.db"}
            )
            Base.metadata.create_all(self._manager.engine)

            self._monkeypatch = pytest.MonkeyPatch()
            self._clock = _Clock(datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc))
            fake_datetime = _make_fake_datetime(self._clock)
            self._monkeypatch.setattr(_collection_module, "datetime", fake_datetime)
            self._monkeypatch.setattr(_publication_module, "datetime", fake_datetime)

            self._collection = CollectionRunWorkflow(
                self._manager, lease_timeout_seconds=LEASE_SECONDS
            )
            self._publication = PublicationRunWorkflow(
                self._manager,
                lease_timeout_seconds=LEASE_SECONDS,
                publication_attempts_dir=root / "attempts",
            )
            self._dispatched: list[tuple[str, int]] = []
            self._patch_noop_dispatch(self._collection, "collection")
            self._patch_noop_dispatch(self._publication, "publication")

            # Hand-computed expected-state model: run_id -> record. Never
            # populated or corrected from `recover_expired_leases()`'s own
            # output.
            self.model: dict[int, dict[str, Any]] = {}
            self._next_article_id = 1000
        except Exception:
            if self._tmpdir is not None:
                self._tmpdir.cleanup()
            raise

    def _patch_noop_dispatch(self, workflow: Any, run_type: str) -> None:
        assert self._monkeypatch is not None

        def _noop(run_id: int, **_kwargs: Any) -> None:
            self._dispatched.append((run_type, run_id))

        self._monkeypatch.setattr(workflow, "_dispatch", _noop)

    def _workflow_for(self, run_type: str) -> Any:
        return self._collection if run_type == "collection" else self._publication

    def _active_id(self, run_type: str) -> int | None:
        active = [
            rid
            for rid, rec in self.model.items()
            if rec["run_type"] == run_type and rec["status"] in ("queued", "running")
        ]
        assert len(active) <= 1, f"model has >1 active {run_type} row: {active}"
        return active[0] if active else None

    def _apply_expected_recovery(
        self, run_type: str, *, include_queued: bool
    ) -> list[int]:
        """Mutates `self.model` to reflect what `recover_expired_leases`
        should do for `run_type`, computed purely from the model's own
        state and `_is_stale_running` -- never from calling the real
        method. Returns the sorted ids expected to be recovered."""
        cutoff = self._clock.now - timedelta(seconds=LEASE_SECONDS)
        recovered: list[int] = []
        for rid, rec in self.model.items():
            if rec["run_type"] != run_type:
                continue
            if rec["status"] == "running" and _is_stale_running(rec, cutoff=cutoff):
                rec["status"] = "interrupted"
                rec["finished_at"] = self._clock.now
                recovered.append(rid)
            elif include_queued and rec["status"] == "queued":
                rec["status"] = "interrupted"
                rec["finished_at"] = self._clock.now
                recovered.append(rid)
        return sorted(recovered)

    def _assert_request_metadata_preserved(
        self, run_id: int, rec: dict[str, Any]
    ) -> None:
        with self._manager.get_session() as session:
            row = session.get(WorkflowRun, run_id)
            metadata = row.run_metadata or {}
        if rec["run_type"] == "collection":
            assert metadata.get("dry_run") == rec["request_metadata"]["dry_run"]
        else:
            assert metadata.get("article_id") == rec["request_metadata"]["article_id"]

    # ------------------------------------------------------------------
    # rules
    # ------------------------------------------------------------------

    @rule(dry_run=st.booleans())
    def start_collection(self, dry_run: bool) -> None:
        self._apply_expected_recovery("collection", include_queued=False)
        active_id = self._active_id("collection")

        result = self._collection.start(dry_run=dry_run)

        if active_id is not None:
            assert result.status == "already_running"
            assert result.run_id == active_id
        else:
            assert result.status == "started"
            self.model[result.run_id] = {
                "run_type": "collection",
                "status": "queued",
                "started_at": self._clock.now,
                "heartbeat_at": None,
                "finished_at": None,
                "request_metadata": {"dry_run": dry_run},
            }

    @rule()
    def start_publication(self) -> None:
        article_id = self._next_article_id
        self._next_article_id += 1

        self._apply_expected_recovery("publication", include_queued=False)
        active_id = self._active_id("publication")

        result = self._publication.start(article_id=article_id)

        if active_id is not None:
            assert result.status == "already_running"
            assert result.run_id == active_id
        else:
            assert result.status == "started"
            self.model[result.run_id] = {
                "run_type": "publication",
                "status": "queued",
                "started_at": self._clock.now,
                "heartbeat_at": None,
                "finished_at": None,
                "request_metadata": {"article_id": article_id, "article_url": None},
            }

    @rule(data=st.data())
    def begin_queued(self, data) -> None:
        if not self.model:
            return
        run_id = data.draw(st.sampled_from(sorted(self.model)))
        rec = self.model[run_id]
        workflow = self._workflow_for(rec["run_type"])

        changed = workflow._transition(
            run_id, from_status="queued", to_status="running"
        )

        if rec["status"] == "queued":
            assert changed is True
            rec["status"] = "running"
        else:
            assert changed is False

    @rule(data=st.data())
    def heartbeat_run(self, data) -> None:
        if not self.model:
            return
        run_id = data.draw(st.sampled_from(sorted(self.model)))
        rec = self.model[run_id]
        workflow = self._workflow_for(rec["run_type"])

        result = workflow.heartbeat(run_id)

        if rec["status"] == "running":
            assert result is True
            rec["heartbeat_at"] = self._clock.now
        else:
            assert result is False

    @rule(data=st.data())
    def complete_run(self, data) -> None:
        if not self.model:
            return
        run_id = data.draw(st.sampled_from(sorted(self.model)))
        rec = self.model[run_id]
        workflow = self._workflow_for(rec["run_type"])

        result = workflow.complete(run_id, summary={"probe": run_id})

        if rec["status"] == "running":
            assert result is True
            rec["status"] = "succeeded"
            rec["finished_at"] = self._clock.now
            self._assert_request_metadata_preserved(run_id, rec)
        else:
            assert result is False

    @rule(data=st.data())
    def fail_run(self, data) -> None:
        if not self.model:
            return
        run_id = data.draw(st.sampled_from(sorted(self.model)))
        rec = self.model[run_id]
        workflow = self._workflow_for(rec["run_type"])

        if rec["run_type"] == "publication":
            result = workflow.fail(
                run_id, error_code="probe_failed", error_detail="probe", summary=None
            )
        else:
            result = workflow.fail(
                run_id, error_code="probe_failed", error_detail="probe"
            )

        if rec["status"] == "running":
            assert result is True
            rec["status"] = "failed"
            rec["finished_at"] = self._clock.now
            self._assert_request_metadata_preserved(run_id, rec)
        else:
            assert result is False

    @rule(run_type=st.sampled_from(["collection", "publication"]))
    def recover_during_service(self, run_type: str) -> None:
        expected = self._apply_expected_recovery(run_type, include_queued=False)
        workflow = self._workflow_for(run_type)

        result = workflow.recover_expired_leases(include_queued=False)

        assert sorted(result) == expected

    @rule(run_type=st.sampled_from(["collection", "publication"]))
    def simulate_boot(self, run_type: str) -> None:
        expected = self._apply_expected_recovery(run_type, include_queued=True)
        assert self._tmpdir is not None
        if run_type == "collection":
            booted: Any = CollectionRunWorkflow(
                self._manager, lease_timeout_seconds=LEASE_SECONDS
            )
        else:
            booted = PublicationRunWorkflow(
                self._manager,
                lease_timeout_seconds=LEASE_SECONDS,
                publication_attempts_dir=Path(self._tmpdir.name) / "attempts",
            )
        self._patch_noop_dispatch(booted, run_type)

        result = booted.recover_expired_leases()

        assert sorted(result) == expected

    @rule(seconds=st.sampled_from([0, 1, 59, 60, 61, 120]))
    def advance_clock(self, seconds: int) -> None:
        # Time change alone must not recover anything -- no model mutation
        # here; only the actions above may transition rows.
        self._clock.advance(seconds)

    # ------------------------------------------------------------------
    # invariant
    # ------------------------------------------------------------------

    @invariant()
    def database_matches_model(self) -> None:
        assert self._manager is not None
        with self._manager.get_session() as session:
            rows = session.execute(select(WorkflowRun)).scalars().all()
            db_state = {
                row.id: {
                    "run_type": row.run_type,
                    "status": row.status,
                    "started_at": _as_utc(row.started_at),
                    "heartbeat_at": _as_utc(row.heartbeat_at),
                    "finished_at": _as_utc(row.finished_at),
                }
                for row in rows
            }

        assert set(db_state) == set(self.model)

        # W1: at most one active (queued/running) row per run_type; a
        # collection row and a publication row may coexist.
        for run_type in ("collection", "publication"):
            active = [
                rid
                for rid, rec in db_state.items()
                if rec["run_type"] == run_type
                and rec["status"] in ("queued", "running")
            ]
            assert len(active) <= 1, f"more than one active {run_type} row: {active}"

        for run_id, expected in self.model.items():
            observed = db_state[run_id]
            assert observed["run_type"] == expected["run_type"]
            assert observed["status"] == expected["status"], (
                run_id,
                observed,
                expected,
            )
            assert observed["started_at"] == expected["started_at"]
            assert observed["heartbeat_at"] == expected["heartbeat_at"]
            assert observed["finished_at"] == expected["finished_at"]

    def teardown(self) -> None:
        if self._monkeypatch is not None:
            self._monkeypatch.undo()
        if self._manager is not None:
            self._manager.close()
        if self._tmpdir is not None:
            self._tmpdir.cleanup()


# Bounded CI profile, not a statistical guarantee (per
# `01-stateful-workflows.md`). Measured at ~1.8s for 20 examples x 20 steps,
# comfortably inside the repository's global 10s pytest timeout -- no
# test-local timeout override needed, and the global timeout in
# `pyproject.toml` is untouched either way.
TestWorkflowLifecycle = WorkflowLifecycleMachine.TestCase
TestWorkflowLifecycle.settings = settings(
    max_examples=20,
    stateful_step_count=20,
    deadline=None,
    derandomize=True,
    database=None,
)
