"""Plan 133: reuse the target frontend checkout between publishes and only
re-install npm dependencies when the manifests changed.

Covers the two seams this plan owns:

- ``publication_pipeline._provision_target_repo`` — reuse vs the historical
  wipe + clone, the structured ``publication.target_repo.reused`` event, and
  the reset that keeps the previous article's branch/working-tree state out
  (caches preserved, stray untracked files removed, remote content restored);
- the dependency fingerprint (``frontend_publication_validation`` +
  ``target_repo_publication``) — install on a fresh checkout, skip with a
  matching marker, re-install when the lock changes, and the marker staying
  outside the writer's ``git add -A`` staging path.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import git
import pytest

from news_collector.components.publishing.github_publisher import GitHubPublisher
from news_collector.logic.workflows.frontend_publication_validation import (
    frontend_dependencies_need_install,
    frontend_dependency_fingerprint,
    frontend_dependency_marker_path,
    read_frontend_dependency_marker,
    run_frontend_publication_validation,
    write_frontend_dependency_marker,
)
from news_collector.logic.workflows.publication_pipeline import _provision_target_repo

_PACKAGE_JSON = {
    "name": "noticiencias-fixture-frontend",
    "version": "1.0.0",
    "private": True,
    "scripts": {"lint": "node -e \"console.log('lint ok')\""},
}
_PACKAGE_LOCK = {
    "name": "noticiencias-fixture-frontend",
    "version": "1.0.0",
    "lockfileVersion": 3,
    "requires": True,
    "packages": {"": {"name": "noticiencias-fixture-frontend", "version": "1.0.0"}},
}


@pytest.fixture
def structured_events(monkeypatch):
    """Capture dict (structured) log events emitted by publication_pipeline.

    Same pattern as the editorial tests: replace the module logger's methods
    and collect the first positional argument when it is a structured payload.
    """
    events: list = []

    def _record(*args, **kwargs):
        events.append(args[0] if args else None)

    import news_collector.logic.workflows.publication_pipeline as pipeline

    monkeypatch.setattr(pipeline.logger, "info", _record)
    monkeypatch.setattr(pipeline.logger, "warning", _record)
    return events


def _write_fixture_remote(
    tmp_path: Path,
    *,
    name: str = "frontend-remote",
    branch: str = "main",
    extra_files: dict[str, str] | None = None,
) -> Path:
    """A minimal git repo shaped like the real frontend checkout.

    ``node_modules``/``dist``/``.astro`` are gitignored exactly like the real
    repository (they are the trees the reuse path must preserve), and the
    sidecar manifest is tracked.
    """
    remote = tmp_path / name
    remote.mkdir(parents=True)
    (remote / ".gitignore").write_text(
        "node_modules/\ndist/\n.astro/\n", encoding="utf-8"
    )
    (remote / "package.json").write_text(
        f"{json.dumps(_PACKAGE_JSON, indent=2)}\n", encoding="utf-8"
    )
    (remote / "package-lock.json").write_text(
        f"{json.dumps(_PACKAGE_LOCK, indent=2)}\n", encoding="utf-8"
    )
    posts = remote / "src" / "content" / "posts"
    posts.mkdir(parents=True)
    (posts / "refinery_manifest.json").write_text("{}\n", encoding="utf-8")
    for relative, content in (extra_files or {}).items():
        path = remote / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    repo = git.Repo.init(remote, initial_branch=branch)
    with repo.config_writer() as config_writer:
        config_writer.set_value("user", "name", "Plan 133 tests")
        config_writer.set_value("user", "email", "tests@example.test")
    repo.git.add(A=True)
    repo.index.commit("Initial fixture frontend")
    return remote


def _make_frontend_checkout(tmp_path: Path) -> Path:
    """A committed, standalone checkout (no remote) for fingerprint tests."""
    checkout = tmp_path / "checkout"
    checkout.mkdir(parents=True)
    (checkout / "package.json").write_text(
        f"{json.dumps(_PACKAGE_JSON, indent=2)}\n", encoding="utf-8"
    )
    (checkout / "package-lock.json").write_text(
        f"{json.dumps(_PACKAGE_LOCK, indent=2)}\n", encoding="utf-8"
    )
    repo = git.Repo.init(checkout, initial_branch="main")
    with repo.config_writer() as config_writer:
        config_writer.set_value("user", "name", "Plan 133 tests")
        config_writer.set_value("user", "email", "tests@example.test")
    repo.git.add(A=True)
    repo.index.commit("Frontend fixture checkout")
    return checkout


def _reuse_events(events: list) -> list:
    return [
        event
        for event in events
        if isinstance(event, dict)
        and event.get("event") == "publication.target_repo.reused"
    ]


# ---------------------------------------------------------------------------
# _provision_target_repo — reuse vs wipe + clone
# ---------------------------------------------------------------------------


def test_provision_clones_when_checkout_is_missing(tmp_path, structured_events) -> None:
    remote = _write_fixture_remote(tmp_path)
    target = tmp_path / "target"

    repo, reused = _provision_target_repo(
        GitHubPublisher(base_branch="main"), str(remote), target
    )

    assert reused is False
    assert (target / ".git").exists()
    assert repo.working_tree_dir is not None
    assert Path(repo.working_tree_dir).resolve() == target.resolve()
    assert _reuse_events(structured_events) == [
        {
            "event": "publication.target_repo.reused",
            "reused": False,
            "target_dir": str(target),
            "reason": "no_checkout",
        }
    ]


def test_provision_reuses_checkout_and_resets_previous_state(
    tmp_path, structured_events
) -> None:
    remote = _write_fixture_remote(tmp_path)
    target = tmp_path / "target"
    handler = GitHubPublisher(base_branch="main")
    _, first_reused = _provision_target_repo(handler, str(remote), target)
    assert first_reused is False

    # The first publish installed dependencies, built, and committed its
    # article on a branch.
    (target / "node_modules" / ".bin").mkdir(parents=True)
    (target / "node_modules" / ".bin" / "sentinel").write_text("keep", encoding="utf-8")
    (target / "dist").mkdir()
    (target / "dist" / "build.js").write_text("built", encoding="utf-8")
    (target / ".astro").mkdir()
    (target / ".astro" / "cache").write_text("cache", encoding="utf-8")
    repo = git.Repo(target)
    with repo.config_writer() as config_writer:
        config_writer.set_value("user", "name", "Plan 133 tests")
        config_writer.set_value("user", "email", "tests@example.test")
    repo.git.checkout("-B", "content/update-old-article")
    (target / "src" / "content" / "posts" / "2026-01-01-old.md").write_text(
        "---\nslug: old\n---\nold article\n", encoding="utf-8"
    )
    repo.git.add(A=True)
    repo.index.commit("Update article: old")
    (target / "stray-untracked.txt").write_text("leftover", encoding="utf-8")

    structured_events.clear()
    _, reused = _provision_target_repo(handler, str(remote), target)

    assert reused is True
    assert _reuse_events(structured_events) == [
        {
            "event": "publication.target_repo.reused",
            "reused": True,
            "target_dir": str(target),
        }
    ]
    # The dependency/build caches the reuse exists to keep survived.
    assert (target / "node_modules" / ".bin" / "sentinel").read_text() == "keep"
    assert (target / "dist" / "build.js").exists()
    assert (target / ".astro" / "cache").exists()
    # The previous article's committed content and stray files did not.
    assert not (target / "src" / "content" / "posts" / "2026-01-01-old.md").exists()
    assert not (target / "stray-untracked.txt").exists()
    assert (target / "src" / "content" / "posts" / "refinery_manifest.json").exists()
    # Deterministic pre-state for the next article.
    check = git.Repo(target)
    assert check.active_branch.name == "main"
    assert check.git.rev_parse("HEAD") == check.git.rev_parse("origin/main")
    assert check.git.status("--porcelain").strip() == ""


def test_provision_wipes_checkout_of_another_remote(
    tmp_path, structured_events
) -> None:
    remote = _write_fixture_remote(tmp_path, name="frontend-remote")
    other = _write_fixture_remote(
        tmp_path,
        name="other-remote",
        extra_files={"other-repo-marker.txt": "other"},
    )
    target = tmp_path / "target"
    handler = GitHubPublisher(base_branch="main")
    _, reused = _provision_target_repo(handler, str(other), target)
    assert reused is False
    assert (target / "other-repo-marker.txt").exists()

    structured_events.clear()
    _, reused = _provision_target_repo(handler, str(remote), target)

    assert reused is False
    assert not (target / "other-repo-marker.txt").exists()
    assert (target / ".git").exists()
    events = _reuse_events(structured_events)
    assert len(events) == 1
    assert events[0]["reused"] is False
    assert events[0]["reason"] == "remote_mismatch"


def test_provision_wipes_non_git_checkout(tmp_path, structured_events) -> None:
    remote = _write_fixture_remote(tmp_path)
    target = tmp_path / "target"
    target.mkdir()
    (target / "junk.txt").write_text("junk", encoding="utf-8")

    _, reused = _provision_target_repo(
        GitHubPublisher(base_branch="main"), str(remote), target
    )

    assert reused is False
    assert not (target / "junk.txt").exists()
    assert (target / "package.json").exists()
    events = _reuse_events(structured_events)
    assert len(events) == 1
    assert events[0]["reason"] == "not_a_git_checkout"


def test_provision_falls_back_to_clone_when_base_ref_is_missing(
    tmp_path, structured_events
) -> None:
    # Expected remote, but its default branch is not ``main`` and the
    # checkout was cloned single-branch: the reset cannot find origin/main.
    remote = _write_fixture_remote(tmp_path, branch="develop")
    target = tmp_path / "target"
    git.Repo.clone_from(str(remote), target, branch="develop")
    (target / "stale.txt").write_text("stale", encoding="utf-8")

    _, reused = _provision_target_repo(
        GitHubPublisher(base_branch="main"), str(remote), target
    )

    assert reused is False
    assert not (target / "stale.txt").exists()
    events = _reuse_events(structured_events)
    assert len(events) == 1
    assert events[0]["reused"] is False
    assert str(events[0]["reason"]).startswith("reset_failed")


# ---------------------------------------------------------------------------
# Dependency fingerprint — install / skip / re-install on lock change
# ---------------------------------------------------------------------------


def test_dependencies_need_install_without_node_modules(tmp_path) -> None:
    checkout = _make_frontend_checkout(tmp_path)
    marker = tmp_path / "runtime" / "frontend_deps" / "marker.json"

    assert frontend_dependencies_need_install(checkout, marker) is True

    # A matching marker alone is not evidence of an installed tree: the
    # checkout can be wiped and re-cloned while the marker survives.
    write_frontend_dependency_marker(
        marker, frontend_dependency_fingerprint(checkout) or ""
    )
    assert frontend_dependencies_need_install(checkout, marker) is True


def test_dependencies_without_marker_record_assumed_provenance(
    tmp_path, monkeypatch
) -> None:
    """A tree that carries dependencies but no marker has unrecorded
    provenance (operator-provisioned checkout, e2e harness fixture). It is
    used as-is — exactly what the pre-plan `node_modules.exists()` rule did —
    but the current fingerprint is recorded as *assumed* so that a later
    manifest change still triggers an install instead of being skipped."""
    from news_collector.logic.workflows import frontend_publication_validation as fvp

    events: list = []
    monkeypatch.setattr(
        fvp.logger, "warning", lambda *a, **k: events.append(a[0] if a else None)
    )
    checkout = _make_frontend_checkout(tmp_path)
    (checkout / "node_modules").mkdir()
    marker = frontend_dependency_marker_path(
        checkout, tmp_path / "runtime" / "frontend_deps"
    )
    fingerprint = frontend_dependency_fingerprint(checkout)

    assert not marker.exists()
    assert frontend_dependencies_need_install(checkout, marker) is False

    structured = [event for event in events if isinstance(event, dict)]
    assert len(structured) == 1
    assert structured[0]["event"] == "publication.frontend_dependencies.assumed"
    assert structured[0]["target_dir"] == str(checkout)
    assert structured[0]["marker_path"] == str(marker)
    assert structured[0]["lock_sha256"] == fingerprint

    recorded = json.loads(marker.read_text(encoding="utf-8"))
    assert recorded["provenance"] == "assumed"
    assert recorded["lock_sha256"] == fingerprint
    assert read_frontend_dependency_marker(marker) == fingerprint

    # The lock change that follows the observation is detected.
    (checkout / "package-lock.json").write_text(
        f"{json.dumps({**_PACKAGE_LOCK, 'lockfileVersion': 2}, indent=2)}\n",
        encoding="utf-8",
    )
    assert frontend_dependencies_need_install(checkout, marker) is True


def test_dependencies_without_recorded_install_keep_previous_behaviour(
    tmp_path,
) -> None:
    """The assumed-provenance write never forces an install that did not
    happen before: a second call with unchanged manifests still skips."""
    checkout = _make_frontend_checkout(tmp_path)
    (checkout / "node_modules").mkdir()
    marker = frontend_dependency_marker_path(
        checkout, tmp_path / "runtime" / "frontend_deps"
    )

    assert frontend_dependencies_need_install(checkout, marker) is False
    assert frontend_dependencies_need_install(checkout, marker) is False


def test_dependencies_skipped_when_lock_and_marker_match(tmp_path) -> None:
    checkout = _make_frontend_checkout(tmp_path)
    (checkout / "node_modules").mkdir()
    marker = frontend_dependency_marker_path(
        checkout, tmp_path / "runtime" / "frontend_deps"
    )

    assert frontend_dependency_fingerprint(checkout) is not None
    write_frontend_dependency_marker(
        marker, frontend_dependency_fingerprint(checkout) or ""
    )

    assert frontend_dependencies_need_install(checkout, marker) is False


def test_dependencies_reinstall_when_lock_changes(tmp_path) -> None:
    checkout = _make_frontend_checkout(tmp_path)
    (checkout / "node_modules").mkdir()
    marker = frontend_dependency_marker_path(
        checkout, tmp_path / "runtime" / "frontend_deps"
    )
    write_frontend_dependency_marker(
        marker, frontend_dependency_fingerprint(checkout) or ""
    )
    assert frontend_dependencies_need_install(checkout, marker) is False

    (checkout / "package-lock.json").write_text(
        f"{json.dumps({**_PACKAGE_LOCK, 'lockfileVersion': 2}, indent=2)}\n",
        encoding="utf-8",
    )

    assert frontend_dependencies_need_install(checkout, marker) is True


def test_dependency_fingerprint_ignores_manifest_formatting(tmp_path) -> None:
    """The gate itself formats the checkout (`npx prettier --write`), so a
    formatting-only rewrite of a manifest must not force a re-install."""
    checkout = _make_frontend_checkout(tmp_path)
    (checkout / "node_modules").mkdir()
    marker = frontend_dependency_marker_path(
        checkout, tmp_path / "runtime" / "frontend_deps"
    )
    fingerprint_before = frontend_dependency_fingerprint(checkout)
    assert frontend_dependencies_need_install(checkout, marker) is False

    (checkout / "package.json").write_text(
        f"{json.dumps(json.loads((checkout / 'package.json').read_text()), indent=4)}\n",
        encoding="utf-8",
    )

    assert frontend_dependency_fingerprint(checkout) == fingerprint_before
    assert frontend_dependencies_need_install(checkout, marker) is False


def test_dependency_marker_path_is_keyed_by_checkout(tmp_path) -> None:
    first = tmp_path / "a"
    second = tmp_path / "b"
    first.mkdir()
    second.mkdir()
    marker_dir = tmp_path / "runtime" / "frontend_deps"

    assert frontend_dependency_marker_path(
        first, marker_dir
    ) == frontend_dependency_marker_path(first, marker_dir)
    assert frontend_dependency_marker_path(
        first, marker_dir
    ) != frontend_dependency_marker_path(second, marker_dir)


def test_frontend_validation_writes_marker_after_successful_install(tmp_path) -> None:
    checkout = _make_frontend_checkout(tmp_path)
    marker = tmp_path / "runtime" / "frontend_deps" / "marker.json"
    executed: list = []

    def runner(command, cwd):
        executed.append(list(command))
        if list(command)[:2] == ["npm", "ci"]:
            # A real `npm ci` materialises node_modules.
            (checkout / "node_modules").mkdir(exist_ok=True)
        return subprocess.CompletedProcess(
            args=list(command), returncode=0, stdout="ok", stderr=""
        )

    summary = run_frontend_publication_validation(
        checkout,
        command_runner=runner,
        stage_fixture=False,
        install_dependencies=True,
        dependency_marker_path=marker,
    )

    assert summary.success is True
    assert [check.name for check in summary.checks] == [
        "npm_ci",
        "publish_image_derivatives",
        "format_repo",
        "lint",
        "validate_content",
        "build",
        "test_dist",
        "test_audit",
    ]
    assert executed[0][:2] == ["npm", "ci"]
    assert read_frontend_dependency_marker(marker) == frontend_dependency_fingerprint(
        checkout
    )
    # A real install records installed provenance, not an assumption.
    assert json.loads(marker.read_text(encoding="utf-8"))["provenance"] == "installed"
    assert frontend_dependencies_need_install(checkout, marker) is False


def test_frontend_validation_does_not_write_marker_when_install_fails(
    tmp_path,
) -> None:
    checkout = _make_frontend_checkout(tmp_path)
    marker = tmp_path / "runtime" / "frontend_deps" / "marker.json"

    def runner(command, cwd):
        returncode = 1 if list(command)[:2] == ["npm", "ci"] else 0
        return subprocess.CompletedProcess(
            args=list(command), returncode=returncode, stdout="", stderr="boom"
        )

    summary = run_frontend_publication_validation(
        checkout,
        command_runner=runner,
        stage_fixture=False,
        install_dependencies=True,
        dependency_marker_path=marker,
    )

    assert summary.success is False
    assert [check.name for check in summary.checks] == ["npm_ci"]
    assert not marker.exists()


def test_frontend_validation_skips_install_when_told_to(tmp_path) -> None:
    checkout = _make_frontend_checkout(tmp_path)

    def runner(command, cwd):
        return subprocess.CompletedProcess(
            args=list(command), returncode=0, stdout="ok", stderr=""
        )

    summary = run_frontend_publication_validation(
        checkout,
        command_runner=runner,
        stage_fixture=False,
        install_dependencies=False,
    )

    assert "npm_ci" not in [check.name for check in summary.checks]


def test_dependency_marker_cannot_be_staged_by_the_writer_commit(tmp_path) -> None:
    """The writer commits with ``git add -A`` inside the checkout; the marker
    lives outside it, so no publish can commit it to the frontend repo."""
    checkout = _make_frontend_checkout(tmp_path)
    marker = frontend_dependency_marker_path(
        checkout, tmp_path / "data" / "runtime" / "frontend_deps"
    )
    write_frontend_dependency_marker(
        marker, frontend_dependency_fingerprint(checkout) or ""
    )

    repo = git.Repo(checkout)
    repo.git.add(A=True)  # GitHubPublisher.commit_and_push's staging selection
    staged = repo.git.diff("--cached", "--name-only")

    assert staged.strip() == ""
    assert repo.git.status("--porcelain").strip() == ""
    assert marker.exists()
    assert checkout.resolve() not in marker.resolve().parents
