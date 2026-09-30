"""
tests/decompose_refinery/test_target_repo_publication.py

Verifies TargetRepoPublicationWorkflow (plan 060 Phase 7b).

Import path after implementation:
    from news_collector.logic.workflows.target_repo_publication import (
        PublicationDeps,
        PublicationOutcome,
        PublicationRequest,
        TargetRepoPublicationWorkflow,
    )
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from news_collector.contracts.publication_validation import PublicationValidationSummary
from news_collector.logic.workflows.target_repo_publication import (
    PublicationDeps,
    PublicationRequest,
    TargetRepoPublicationWorkflow,
)

MODULE = "news_collector.logic.workflows.target_repo_publication"


class StageLog:
    """`record_stage` callback that records ordered calls."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, bool, dict]] = []

    def __call__(self, name: str, success: bool, **details) -> None:
        self.calls.append((name, success, details))

    @property
    def names(self) -> list[str]:
        return [call[0] for call in self.calls]

    def get(self, name: str) -> list[tuple[str, bool, dict]]:
        return [call for call in self.calls if call[0] == name]


def _request(tmp_path: Path, **overrides) -> PublicationRequest:
    target_dir = tmp_path / "target"
    (target_dir / "src/content/posts").mkdir(parents=True)
    defaults = {
        "article": {"id": "42", "url": "https://example.com/a"},
        "article_id": "42",
        "numeric_id": 42,
        "output_filename": "2024-01-25-test.md",
        "refined_content": "---\ntitle: T\n---\nBody",
        "grounding_notes": "notes",
        "target_repo_obj": MagicMock(),
        "target_dir": target_dir,
        "attempts_dir": tmp_path / "attempts",
    }
    defaults.update(overrides)
    return PublicationRequest(**defaults)


def _deps(**overrides) -> PublicationDeps:
    git = MagicMock()
    git.create_branch.return_value = "content/update-2024-01-25-test"
    pr_orchestrator = MagicMock()
    pr_orchestrator.create_pr.return_value = SimpleNamespace(
        pr_url="https://github.com/org/repo/pull/1"
    )
    defaults = {
        "writer": MagicMock(),
        "git": git,
        "pr_orchestrator": pr_orchestrator,
        "db": MagicMock(),
    }
    defaults.update(overrides)
    return PublicationDeps(**defaults)


def _publish(request, deps, stages: StageLog):
    return TargetRepoPublicationWorkflow().publish(request, deps, stages)


# ---------------------------------------------------------------------------
# happy path / stage order
# ---------------------------------------------------------------------------


class TestHappyPath:
    def test_without_frontend_workspace_skips_validation(self, tmp_path: Path):
        request = _request(tmp_path)
        deps = _deps()
        stages = StageLog()

        outcome = _publish(request, deps, stages)

        assert outcome.success is True
        assert outcome.branch_name == "content/update-2024-01-25-test"
        assert outcome.pr_url == "https://github.com/org/repo/pull/1"
        assert outcome.failure_class is None
        assert stages.names == [
            "branch_created",
            "file_written",
            "frontend_publication_validation",
            "commit_pushed",
            "pr_created",
        ]
        skipped = stages.get("frontend_publication_validation")[0][2]
        assert skipped["skipped"] is True
        assert skipped["reason"] == "frontend_workspace_not_detected"

        deps.writer.write_article.assert_called_once()
        deps.git.commit_and_push.assert_called_once()
        deps.pr_orchestrator.create_pr.assert_called_once()

    def test_full_validation_success_records_summary_path(self, tmp_path: Path):
        request = _request(tmp_path)
        (request.target_dir / "package.json").write_text("{}", encoding="utf-8")
        deps = _deps()
        stages = StageLog()
        summary = PublicationValidationSummary(
            generated_at="2026-05-08T12:00:00Z",
            frontend_root=str(request.target_dir),
            post_path=str(request.target_dir / "src/content/posts/x.md"),
            manifest_path=str(request.target_dir / "src/content/posts/m.json"),
            success=True,
            checks=[],
        )

        with (
            patch(
                f"{MODULE}.validate_post_frontmatter_fast",
                return_value=(True, None, None),
            ),
            patch(
                f"{MODULE}.run_frontend_publication_validation", return_value=summary
            ),
        ):
            outcome = _publish(request, deps, stages)

        assert outcome.success is True
        assert outcome.validation_summary_path is not None
        assert outcome.validation_summary_path.endswith("42.frontend_validation.json")
        validation_stage = stages.get("frontend_publication_validation")[0]
        assert validation_stage[1] is True
        assert validation_stage[2]["summary_path"] == outcome.validation_summary_path


# ---------------------------------------------------------------------------
# failure paths
# ---------------------------------------------------------------------------


class TestFailurePaths:
    def test_missing_output_filename_fails_before_side_effects(self, tmp_path: Path):
        request = _request(tmp_path, output_filename=None)
        deps = _deps()
        stages = StageLog()

        outcome = _publish(request, deps, stages)

        assert outcome.success is False
        assert outcome.branch_name is None
        assert stages.names == ["output_filename"]
        deps.git.create_branch.assert_not_called()
        deps.writer.write_article.assert_not_called()

    def test_writer_value_error_records_failure_without_commit(self, tmp_path: Path):
        request = _request(tmp_path)
        deps = _deps()
        deps.writer.write_article.side_effect = ValueError("bad write")
        stages = StageLog()

        outcome = _publish(request, deps, stages)

        assert outcome.success is False
        assert outcome.branch_name == "content/update-2024-01-25-test"
        assert stages.names == [
            "branch_created",
            "file_written",
            "publishing_state_released",
        ]
        assert stages.get("file_written")[0][1] is False
        assert stages.get("file_written")[0][2]["error"] == "bad write"
        deps.git.commit_and_push.assert_not_called()
        deps.pr_orchestrator.create_pr.assert_not_called()
        deps.db.release_article_publishing.assert_called_once_with(
            42, reason="file_write_failed", failure_class=None
        )

    def test_fast_frontmatter_failure_skips_full_validation(self, tmp_path: Path):
        request = _request(tmp_path)
        (request.target_dir / "package.json").write_text("{}", encoding="utf-8")
        deps = _deps()
        stages = StageLog()

        with (
            patch(
                f"{MODULE}.validate_post_frontmatter_fast",
                return_value=(
                    False,
                    "taxonomy_contract_violation",
                    "sources[].date: null",
                ),
            ),
            patch(f"{MODULE}.run_frontend_publication_validation") as full,
        ):
            outcome = _publish(request, deps, stages)

        assert outcome.success is False
        assert outcome.failure_class == "taxonomy_contract_violation"
        assert outcome.validation_summary_path is not None
        full.assert_not_called()
        failed = stages.get("frontend_publication_validation")[0]
        assert failed[1] is False
        assert failed[2]["fast"] is True
        deps.git.commit_and_push.assert_not_called()

    def test_fast_frontmatter_failure_without_class_uses_taxonomy_fallback(
        self, tmp_path: Path
    ):
        request = _request(tmp_path)
        (request.target_dir / "package.json").write_text("{}", encoding="utf-8")
        deps = _deps()
        stages = StageLog()

        with patch(
            f"{MODULE}.validate_post_frontmatter_fast",
            return_value=(False, None, "unclassified"),
        ):
            outcome = _publish(request, deps, stages)

        assert outcome.failure_class == "taxonomy_contract_violation"

    def test_full_validation_failure_carries_failure_class(self, tmp_path: Path):
        request = _request(tmp_path)
        (request.target_dir / "package.json").write_text("{}", encoding="utf-8")
        deps = _deps()
        stages = StageLog()
        summary = PublicationValidationSummary(
            generated_at="2026-05-08T12:00:00Z",
            frontend_root=str(request.target_dir),
            post_path=str(request.target_dir / "src/content/posts/x.md"),
            manifest_path=str(request.target_dir / "src/content/posts/m.json"),
            success=False,
            overall_failure_class="frontend_build_failure",
            checks=[],
        )

        with (
            patch(
                f"{MODULE}.validate_post_frontmatter_fast",
                return_value=(True, None, None),
            ),
            patch(
                f"{MODULE}.run_frontend_publication_validation", return_value=summary
            ),
        ):
            outcome = _publish(request, deps, stages)

        assert outcome.success is False
        assert outcome.failure_class == "frontend_build_failure"
        deps.git.commit_and_push.assert_not_called()
        deps.pr_orchestrator.create_pr.assert_not_called()

    def test_pr_none_records_failure(self, tmp_path: Path):
        request = _request(tmp_path)
        deps = _deps()
        deps.pr_orchestrator.create_pr.return_value = SimpleNamespace(pr_url=None)
        stages = StageLog()

        outcome = _publish(request, deps, stages)

        assert outcome.success is False
        assert outcome.pr_url is None
        assert stages.get("pr_created")[0][1] is False
        deps.git.commit_and_push.assert_called_once()

    def test_falsy_pr_url_is_preserved_for_persistence(self, tmp_path: Path):
        request = _request(tmp_path)
        deps = _deps()
        deps.pr_orchestrator.create_pr.return_value = SimpleNamespace(pr_url="")
        stages = StageLog()

        outcome = _publish(request, deps, stages)

        assert outcome.success is False
        assert outcome.pr_url == ""
        assert stages.get("pr_created")[0][1] is False


# ---------------------------------------------------------------------------
# self-healing: bounded content repair + publishing-state release
# ---------------------------------------------------------------------------

POST_WITH_BAD_TAG = """---
title: La gravedad
tags:
  - ads/cft
  - gravedad
---

Body
"""


def _summary(
    target_dir: Path, *, success: bool, failure_class=None
) -> PublicationValidationSummary:
    return PublicationValidationSummary(
        generated_at="2026-05-08T12:00:00Z",
        frontend_root=str(target_dir),
        post_path=str(target_dir / "src/content/posts/x.md"),
        manifest_path=str(target_dir / "src/content/posts/m.json"),
        success=success,
        overall_failure_class=failure_class,
        checks=[],
    )


def _write_post_file(request: PublicationRequest) -> Path:
    post_path = request.target_dir / "src/content/posts" / request.output_filename
    post_path.write_text(POST_WITH_BAD_TAG, encoding="utf-8")
    return post_path


class TestSelfHealingRepair:
    def _prepared_request(self, tmp_path: Path) -> PublicationRequest:
        request = _request(tmp_path)
        (request.target_dir / "package.json").write_text("{}", encoding="utf-8")
        return request

    def test_full_validation_failure_is_repaired_and_publishes(self, tmp_path: Path):
        request = self._prepared_request(tmp_path)
        post_path = _write_post_file(request)
        deps = _deps()
        stages = StageLog()
        summaries = [
            _summary(
                request.target_dir,
                success=False,
                failure_class="taxonomy_contract_violation",
            ),
            _summary(request.target_dir, success=True),
        ]
        with (
            patch(
                f"{MODULE}.validate_post_frontmatter_fast",
                return_value=(True, None, None),
            ),
            patch(
                f"{MODULE}.run_frontend_publication_validation",
                side_effect=summaries,
            ),
        ):
            outcome = _publish(request, deps, stages)

        assert outcome.success is True
        repaired = post_path.read_text(encoding="utf-8")
        assert "ads/cft" not in repaired
        assert "ads cft" in repaired
        repair_stage = stages.get("validation_self_repair")
        assert repair_stage and repair_stage[0][1] is True
        assert repair_stage[0][2]["failure_class"] == "taxonomy_contract_violation"
        deps.git.commit_and_push.assert_called_once()
        deps.db.release_article_publishing.assert_not_called()

    def test_repair_is_bounded_when_revalidation_still_fails(self, tmp_path: Path):
        request = self._prepared_request(tmp_path)
        _write_post_file(request)
        deps = _deps()
        stages = StageLog()
        summaries = [
            _summary(
                request.target_dir,
                success=False,
                failure_class="taxonomy_contract_violation",
            ),
            _summary(
                request.target_dir,
                success=False,
                failure_class="frontend_build_failure",
            ),
        ]
        with (
            patch(
                f"{MODULE}.validate_post_frontmatter_fast",
                return_value=(True, None, None),
            ),
            patch(
                f"{MODULE}.run_frontend_publication_validation",
                side_effect=summaries,
            ) as run,
        ):
            outcome = _publish(request, deps, stages)

        assert outcome.success is False
        assert outcome.failure_class == "frontend_build_failure"
        assert run.call_count == 2  # one repair attempt, never a loop
        assert len(stages.get("validation_self_repair")) == 1
        deps.git.commit_and_push.assert_not_called()

    def test_unrepairable_failure_is_not_retried(self, tmp_path: Path):
        request = self._prepared_request(tmp_path)
        _write_post_file(request)
        deps = _deps()
        stages = StageLog()
        failed = _summary(
            request.target_dir,
            success=False,
            failure_class="frontend_build_failure",
        )
        with (
            patch(
                f"{MODULE}.validate_post_frontmatter_fast",
                return_value=(True, None, None),
            ),
            patch(
                f"{MODULE}.run_frontend_publication_validation", return_value=failed
            ) as run,
        ):
            outcome = _publish(request, deps, stages)

        assert outcome.success is False
        assert run.call_count == 1
        assert stages.get("validation_self_repair") == []
        deps.git.commit_and_push.assert_not_called()

    def test_fast_guard_failure_is_repaired_before_full_validation(
        self, tmp_path: Path
    ):
        request = self._prepared_request(tmp_path)
        post_path = _write_post_file(request)
        deps = _deps()
        stages = StageLog()
        fast_results = [
            (False, "taxonomy_contract_violation", "tags"),
            (True, None, None),
        ]
        with (
            patch(
                f"{MODULE}.validate_post_frontmatter_fast",
                side_effect=fast_results,
            ),
            patch(
                f"{MODULE}.run_frontend_publication_validation",
                return_value=_summary(request.target_dir, success=True),
            ) as run,
        ):
            outcome = _publish(request, deps, stages)

        assert outcome.success is True
        assert run.call_count == 1
        assert "ads cft" in post_path.read_text(encoding="utf-8")
        assert stages.get("validation_self_repair")

    def test_release_on_validation_failure(self, tmp_path: Path):
        request = self._prepared_request(tmp_path)
        _write_post_file(request)
        deps = _deps()
        stages = StageLog()
        failed = _summary(
            request.target_dir,
            success=False,
            failure_class="frontend_build_failure",
        )
        with (
            patch(
                f"{MODULE}.validate_post_frontmatter_fast",
                return_value=(True, None, None),
            ),
            patch(f"{MODULE}.run_frontend_publication_validation", return_value=failed),
        ):
            outcome = _publish(request, deps, stages)

        assert outcome.success is False
        deps.db.release_article_publishing.assert_called_once_with(
            42,
            reason="frontend_validation_failed",
            failure_class="frontend_build_failure",
        )
        released = stages.get("publishing_state_released")
        assert released and released[0][1] is True

    def test_release_skipped_without_db_method(self, tmp_path: Path):
        request = self._prepared_request(tmp_path)
        _write_post_file(request)
        deps = _deps(db=SimpleNamespace())
        stages = StageLog()
        failed = _summary(
            request.target_dir,
            success=False,
            failure_class="frontend_build_failure",
        )
        with (
            patch(
                f"{MODULE}.validate_post_frontmatter_fast",
                return_value=(True, None, None),
            ),
            patch(f"{MODULE}.run_frontend_publication_validation", return_value=failed),
        ):
            outcome = _publish(request, deps, stages)

        assert outcome.success is False
        assert "publishing_state_released" not in stages.names

    def test_pr_failure_keeps_publishing_state_for_recovery(self, tmp_path: Path):
        request = _request(tmp_path)
        deps = _deps()
        deps.pr_orchestrator.create_pr.return_value = SimpleNamespace(pr_url=None)
        stages = StageLog()

        outcome = _publish(request, deps, stages)

        assert outcome.success is False
        deps.db.release_article_publishing.assert_not_called()
        assert "publishing_state_released" not in stages.names


# ---------------------------------------------------------------------------
# publishing mark and dependency seams
# ---------------------------------------------------------------------------


class TestPublishingMark:
    def test_marks_publishing_before_branch_creation(self, tmp_path: Path):
        request = _request(tmp_path)
        events: list[str] = []
        db = MagicMock()
        db.mark_article_publishing.side_effect = lambda *a, **k: events.append("mark")
        git = MagicMock()
        git.create_branch.side_effect = lambda *a, **k: (
            events.append("branch") or "content/update-x"
        )
        deps = _deps(db=db, git=git)

        _publish(request, deps, StageLog())

        assert events == ["mark", "branch"]
        db.mark_article_publishing.assert_called_once_with(
            42, "content/update-2024-01-25-test"
        )

    def test_skips_mark_when_db_lacks_method(self, tmp_path: Path):
        request = _request(tmp_path)
        deps = _deps(db=SimpleNamespace())
        stages = StageLog()

        outcome = _publish(request, deps, stages)

        assert outcome.success is True

    def test_swallows_mark_failure(self, tmp_path: Path):
        request = _request(tmp_path)
        db = MagicMock()
        db.mark_article_publishing.side_effect = RuntimeError("db down")
        deps = _deps(db=db)
        stages = StageLog()

        outcome = _publish(request, deps, stages)

        assert outcome.success is True
        assert "branch_created" in stages.names

    def test_no_mark_when_numeric_id_missing(self, tmp_path: Path):
        request = _request(tmp_path, numeric_id=None)
        deps = _deps()
        stages = StageLog()

        _publish(request, deps, stages)

        deps.db.mark_article_publishing.assert_not_called()

    def test_collaborators_come_from_deps_per_call(self, tmp_path: Path):
        request = _request(tmp_path)
        first_git = MagicMock()
        first_git.create_branch.return_value = "content/update-first"
        second_git = MagicMock()
        second_git.create_branch.return_value = "content/update-second"

        first = _publish(request, _deps(git=first_git), StageLog())
        second = _publish(request, _deps(git=second_git), StageLog())

        assert first.branch_name == "content/update-first"
        assert second.branch_name == "content/update-second"
