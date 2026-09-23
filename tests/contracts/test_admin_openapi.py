"""Plan 080 Phase 2 — admin OpenAPI artifact: determinism, isolation, drift.

Acceptance coverage (see `plans/080/02-admin-contracts.md`):
- A1: export runs without credentials/network/production files, never uses the
  default database manager, and never enters the lifespan (no recovery).
- A2: fresh exports are byte-identical; check fails on stale/missing artifacts.
- A5: checks never repair a stale artifact.
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.export_admin_openapi import main, render_document

REPO_ROOT = Path(__file__).resolve().parents[2]
ARTIFACT = REPO_ROOT / "apps" / "admin" / "openapi.json"


def test_export_is_deterministic_and_valid_json() -> None:
    first = render_document()
    second = render_document()

    assert first == second
    assert first.endswith(b"\n")
    document = json.loads(first.decode("utf-8"))
    assert document["openapi"].startswith("3.")
    assert "paths" in document and "components" in document


def test_export_never_uses_the_default_database_manager_or_recovery(
    monkeypatch,
) -> None:
    import news_collector.serving.api as api_module
    from news_collector.logic.workflows.collection_run_workflow import (
        CollectionRunWorkflow,
    )
    from news_collector.logic.workflows.publication_run_workflow import (
        PublicationRunWorkflow,
    )

    def _boom(*_args, **_kwargs):  # pragma: no cover - only on regression
        raise AssertionError("schema export must not touch production state")

    monkeypatch.setattr(api_module, "get_database_manager", _boom)
    monkeypatch.setattr(CollectionRunWorkflow, "recover_expired_leases", _boom)
    monkeypatch.setattr(PublicationRunWorkflow, "recover_expired_leases", _boom)

    document = json.loads(render_document().decode("utf-8"))
    assert document["openapi"].startswith("3.")


def test_check_passes_on_the_committed_artifact() -> None:
    assert ARTIFACT.exists(), "run `make admin-contracts-generate` first"
    assert main(["--check", str(ARTIFACT)]) == 0


def test_check_fails_and_never_repairs_a_stale_artifact(tmp_path, capsys) -> None:
    stale = tmp_path / "openapi.json"
    stale.write_text('{"openapi": "3.1.0"}\n', encoding="utf-8")
    before = stale.read_bytes()

    assert main(["--check", str(stale)]) == 1

    assert stale.read_bytes() == before
    assert "stale artifact" in capsys.readouterr().err


def test_check_fails_when_the_artifact_is_missing(tmp_path, capsys) -> None:
    missing = tmp_path / "does-not-exist.json"

    assert main(["--check", str(missing)]) == 1

    assert "missing artifact" in capsys.readouterr().err


def test_output_writes_the_document(tmp_path) -> None:
    target = tmp_path / "nested" / "openapi.json"

    assert main(["--output", str(target)]) == 0

    assert target.read_bytes() == render_document()
