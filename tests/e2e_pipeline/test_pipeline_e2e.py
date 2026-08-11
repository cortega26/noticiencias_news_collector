from __future__ import annotations

import json
import os
import shutil
import socket
from pathlib import Path

import pytest

from news_collector.logic.workflows.pipeline_e2e import (
    FRONTEND_COPY_IGNORE,
    NODE_MODULES_COPY_IGNORE,
    run_pipeline_e2e_scenario,
)

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "pipeline_e2e"
# The repeatability test runs the full pipeline twice; under full-suite
# load (make type / verify-ci with coverage instrumentation) two runs
# exceed 180s. 300s covers the worst observed case with margin.
pytestmark = pytest.mark.timeout(300)


@pytest.mark.parametrize(
    ("fixture_name", "expected_success", "expected_root_failure_stage"),
    [
        ("happy_path_latam_winner", True, None),
        ("blocked_source_fallback", False, "selection"),
        ("low_value_beats_high_value_regression", True, None),
        ("frontend_rejects_generated_post", False, "frontend_validation"),
        ("stuck_publishing_recovery", True, None),
        ("duplicate_permalink_collision", False, "frontend_validation"),
    ],
)
def test_pipeline_e2e_scenarios(
    tmp_path: Path,
    fixture_name: str,
    expected_success: bool,
    expected_root_failure_stage: str | None,
) -> None:
    bundle_root = tmp_path / fixture_name
    summary = run_pipeline_e2e_scenario(
        FIXTURE_DIR / f"{fixture_name}.json",
        bundle_root=bundle_root,
    )

    assert summary.success is expected_success
    assert summary.root_failure_stage == expected_root_failure_stage
    assert (bundle_root / "run_summary.json").exists()
    assert (bundle_root / "artifacts" / "collection_report.json").exists()
    assert (bundle_root / "artifacts" / "latest_articles.json").exists()
    assert summary.stages
    assert {stage.stage for stage in summary.stages} >= {
        "collection",
        "validation",
        "scoring",
        "export",
        "selection",
        "approval",
        "publication",
        "frontend_validation",
    }


def test_blocked_source_fallback_persists_rejected_candidate(tmp_path: Path) -> None:
    bundle_root = tmp_path / "blocked_source_fallback"
    summary = run_pipeline_e2e_scenario(
        FIXTURE_DIR / "blocked_source_fallback.json",
        bundle_root=bundle_root,
    )

    assert summary.success is False
    assert summary.root_failure_stage == "selection"

    db_snapshot = json.loads(
        (bundle_root / "artifacts" / "db_snapshot.json").read_text(encoding="utf-8")
    )
    assert len(db_snapshot["rejected"]) == 1
    assert (
        db_snapshot["rejected"][0]["article_metadata"]["source_metadata"][
            "stage_b_failure_reason"
        ]
        == "content_too_short_for_publication"
    )


def test_frontend_validation_failure_is_classified_for_taxonomy_and_permalink(
    tmp_path: Path,
) -> None:
    taxonomy_bundle = tmp_path / "frontend_rejects_generated_post"
    taxonomy_summary = run_pipeline_e2e_scenario(
        FIXTURE_DIR / "frontend_rejects_generated_post.json",
        bundle_root=taxonomy_bundle,
    )
    taxonomy_payload = json.loads(
        Path(taxonomy_summary.frontend_validation_summary_path).read_text(
            encoding="utf-8"
        )
    )
    assert taxonomy_payload["overall_failure_class"] == "taxonomy_contract_violation"

    permalink_bundle = tmp_path / "duplicate_permalink_collision"
    permalink_summary = run_pipeline_e2e_scenario(
        FIXTURE_DIR / "duplicate_permalink_collision.json",
        bundle_root=permalink_bundle,
    )
    permalink_payload = json.loads(
        Path(permalink_summary.frontend_validation_summary_path).read_text(
            encoding="utf-8"
        )
    )
    assert permalink_payload["overall_failure_class"] == "permalink_collision"


def test_recovery_scenario_records_publishing_recovery(tmp_path: Path) -> None:
    bundle_root = tmp_path / "stuck_publishing_recovery"
    summary = run_pipeline_e2e_scenario(
        FIXTURE_DIR / "stuck_publishing_recovery.json",
        bundle_root=bundle_root,
    )

    assert summary.success is True
    publication_attempt = json.loads(
        Path(summary.publication_attempt_summary_path).read_text(encoding="utf-8")
    )
    stage_names = [stage["name"] for stage in publication_attempt["stages"]]
    assert "publishing_recovery" in stage_names
    assert summary.frontend_validation_summary_path is None


def test_happy_path_captures_generated_markdown_artifact(tmp_path: Path) -> None:
    bundle_root = tmp_path / "happy_path_latam_winner"
    summary = run_pipeline_e2e_scenario(
        FIXTURE_DIR / "happy_path_latam_winner.json",
        bundle_root=bundle_root,
    )

    publication_stage = next(
        stage for stage in summary.stages if stage.stage == "publication"
    )
    generated_post_path = publication_stage.details.get("generated_post_path")

    assert summary.success is True
    assert generated_post_path
    assert Path(str(generated_post_path)).exists()


def test_pipeline_e2e_bundle_root_is_repeatable(tmp_path: Path) -> None:
    bundle_root = tmp_path / "happy_path_repeatable"

    first = run_pipeline_e2e_scenario(
        FIXTURE_DIR / "happy_path_latam_winner.json",
        bundle_root=bundle_root,
    )
    second = run_pipeline_e2e_scenario(
        FIXTURE_DIR / "happy_path_latam_winner.json",
        bundle_root=bundle_root,
    )

    assert first.success is True
    assert second.success is True
    assert first.selected_article_id == second.selected_article_id
    assert first.root_failure_stage is None
    assert second.root_failure_stage is None


def _create_special_files(source: Path) -> None:
    """Crea un socket Unix real y una FIFO dentro de *source*."""
    sock_path = source / "daemon.sock"
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.bind(str(sock_path))
    finally:
        sock.close()
    os.mkfifo(source / "build_pipe.fifo")


def test_frontend_copy_ignore_skips_sockets_and_fifos(tmp_path: Path) -> None:
    source = tmp_path / "frontend_source"
    source.mkdir()
    (source / "regular.txt").write_text("contenido", encoding="utf-8")
    (source / ".git").mkdir()
    _create_special_files(source)

    target = tmp_path / "frontend_target"
    shutil.copytree(source, target, ignore=FRONTEND_COPY_IGNORE)

    assert (target / "regular.txt").read_text(encoding="utf-8") == "contenido"
    assert not (target / ".git").exists()
    assert not (target / "daemon.sock").exists()
    assert not (target / "build_pipe.fifo").exists()


def test_node_modules_copy_ignore_skips_sockets(tmp_path: Path) -> None:
    source = tmp_path / "node_modules_source"
    source.mkdir()
    (source / "package.json").write_text("{}", encoding="utf-8")
    (source / ".cache").mkdir()
    sock_path = source / "daemon.sock"
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.bind(str(sock_path))
    finally:
        sock.close()

    target = tmp_path / "node_modules_target"
    shutil.copytree(source, target, ignore=NODE_MODULES_COPY_IGNORE)

    assert (target / "package.json").read_text(encoding="utf-8") == "{}"
    assert not (target / ".cache").exists()
    assert not (target / "daemon.sock").exists()
