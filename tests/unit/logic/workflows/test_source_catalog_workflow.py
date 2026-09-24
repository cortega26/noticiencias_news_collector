"""Plan 060 / Phase 4b — SourceCatalogWorkflow safety tests.

Covers: atomic writes (a simulated replace failure never corrupts the live
file), the advisory lock (contention times out with a typed result), DB-sync
compensation (YAML restored), the reconciliation marker when the restore
itself fails, validation-before-write, and the typed not-found rejection.
"""

from __future__ import annotations

import fcntl
import os
from pathlib import Path

import pytest
import yaml

from news_collector.logic.workflows.source_catalog_workflow import (
    RUN_TYPE_SOURCE_CATALOG_RECONCILIATION,
    SourceCatalogMutationRejected,
    SourceCatalogWorkflow,
)
from news_collector.storage.database import DatabaseManager
from news_collector.storage.models import Base, WorkflowRun


@pytest.fixture()
def db_manager(tmp_path):
    db_file = tmp_path / "source_catalog_workflow.db"
    manager = DatabaseManager({"type": "sqlite", "path": db_file})
    Base.metadata.create_all(manager.engine)
    yield manager
    manager.close()


VALID_ENTRY = {
    "name": "Example",
    "url": "https://example.com/feed",
    "credibility_score": 0.8,
    "category": "science",
    "tier": "D",
    "fetchability_score": 50,
    "crawl_interval_seconds": 86400,
}


@pytest.fixture()
def catalog_path(tmp_path) -> Path:
    path = tmp_path / "sources.yaml"
    path.write_text(
        yaml.safe_dump({"one": dict(VALID_ENTRY)}, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return path


@pytest.fixture()
def workflow(db_manager, catalog_path) -> SourceCatalogWorkflow:
    return SourceCatalogWorkflow(
        db_manager, sources_yaml_path=catalog_path, lock_timeout_seconds=0.2
    )


def _read(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def test_load_reads_fresh_on_disk_content(workflow, catalog_path) -> None:
    assert "one" in workflow.load()

    catalog_path.write_text(
        yaml.safe_dump({"two": dict(VALID_ENTRY)}, sort_keys=False), encoding="utf-8"
    )

    assert list(workflow.load()) == ["two"]


def test_mutate_writes_candidate_and_syncs_db(
    workflow, catalog_path, db_manager
) -> None:
    synced: list[dict] = []

    result = workflow.mutate(
        lambda catalog: {**catalog, "two": dict(VALID_ENTRY)},
        db_sync_fn=synced.append,
    )

    assert result.status == "ok"
    assert set(_read(catalog_path)) == {"one", "two"}
    assert len(synced) == 1


def test_validation_failure_writes_nothing(workflow, catalog_path) -> None:
    before = catalog_path.read_text(encoding="utf-8")

    result = workflow.mutate(lambda catalog: {**catalog, "bad": {"name": "x"}})

    assert result.status == "validation_failed"
    assert catalog_path.read_text(encoding="utf-8") == before


def test_atomic_write_failure_leaves_original_intact(
    workflow, catalog_path, monkeypatch
) -> None:
    before = catalog_path.read_text(encoding="utf-8")

    def _explode(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", _explode)

    with pytest.raises(OSError):
        workflow.mutate(lambda catalog: {**catalog, "two": dict(VALID_ENTRY)})

    assert catalog_path.read_text(encoding="utf-8") == before
    leftovers = [
        p for p in catalog_path.parent.iterdir() if p.name.startswith(".sources.yaml-")
    ]
    assert leftovers == []


def test_db_sync_failure_restores_prior_yaml(workflow, catalog_path) -> None:
    before = catalog_path.read_text(encoding="utf-8")

    def _fail(_catalog):
        raise RuntimeError("db down")

    result = workflow.mutate(
        lambda catalog: {**catalog, "two": dict(VALID_ENTRY)}, db_sync_fn=_fail
    )

    assert result.status == "db_sync_failed"
    assert catalog_path.read_text(encoding="utf-8") == before


def test_restore_failure_records_reconciliation_marker(
    workflow, catalog_path, db_manager, monkeypatch
) -> None:
    real_replace = os.replace
    calls = {"n": 0}

    def _fail_second_replace(src, dst):
        calls["n"] += 1
        if calls["n"] == 2:  # first write succeeds, restore fails
            raise OSError("disk full during restore")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", _fail_second_replace)

    def _fail(_catalog):
        raise RuntimeError("db down")

    result = workflow.mutate(
        lambda catalog: {**catalog, "two": dict(VALID_ENTRY)}, db_sync_fn=_fail
    )

    assert result.status == "reconciliation_required"
    with db_manager.get_session() as session:
        rows = (
            session.query(WorkflowRun)
            .filter(WorkflowRun.run_type == RUN_TYPE_SOURCE_CATALOG_RECONCILIATION)
            .all()
        )
    assert len(rows) == 1
    assert rows[0].error_code == "reconciliation_required"
    assert "db down" in (rows[0].error_detail or "")


def test_mutation_rejection_maps_to_not_found(workflow, catalog_path) -> None:
    before = catalog_path.read_text(encoding="utf-8")

    def _reject(_catalog):
        raise SourceCatalogMutationRejected("Source not found")

    result = workflow.mutate(_reject)

    assert result.status == "not_found"
    assert catalog_path.read_text(encoding="utf-8") == before


def test_lock_contention_times_out_without_touching_the_file(
    workflow, catalog_path
) -> None:
    before = catalog_path.read_text(encoding="utf-8")
    lock_fd = os.open(workflow.lock_path, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

        result = workflow.mutate(lambda catalog: {**catalog, "two": dict(VALID_ENTRY)})

        assert result.status == "catalog_locked"
        assert catalog_path.read_text(encoding="utf-8") == before
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)


def test_unreadable_catalog_is_a_typed_validation_failure(
    workflow, catalog_path
) -> None:
    catalog_path.write_text("- just\n- a list\n", encoding="utf-8")

    result = workflow.mutate(lambda catalog: catalog)

    assert result.status == "validation_failed"
    assert "ilegible" in result.detail
