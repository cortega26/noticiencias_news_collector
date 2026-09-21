"""Unit tests for scripts/generate_inventory.py tracked-path filtering.

Root fix for issue #264: the workdir-verbatim listings folded
environment-dependent runtime state (`data/image-uploads/`, `data/data/`,
`.test_venv/`, …) into the snapshot, so any baseline generated from a
lived-in workdir drifted forever against fresh CI checkouts.
"""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import generate_inventory as inventory


@pytest.fixture()
def workdir(tmp_path, monkeypatch):
    """Fake repo: tracked source layout plus untracked runtime noise."""
    tracked = {
        "README.md",
        "Makefile",
        "data/exports/latest_articles.json",
        "data/image-briefs/2026-05-22-brief.json",
        "src/a.py",
        "docs/guide.md",
    }
    for rel in tracked:
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("tracked", encoding="utf-8")
    runtime = [
        "data/image-uploads/x.jpg",
        "data/data/y",
        "notes-scratch.md",
        "temp/source/notes.md",
    ]
    for rel in runtime:
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("runtime", encoding="utf-8")
    monkeypatch.setattr(inventory, "_tracked_paths", lambda root: set(tracked))
    return tmp_path


def test_top_level_ignores_untracked_runtime_dirs(workdir):
    listing = inventory._list_top_level(workdir)

    assert "data/" in listing
    assert listing["data/"] == ["exports", "image-briefs"]
    assert "notes-scratch.md" not in listing
    assert "temp/" not in listing
    assert listing["src/"] == ["a.py"]
    assert "README.md" in listing


def test_top_level_fail_open_without_git(workdir, monkeypatch):
    monkeypatch.setattr(inventory, "_tracked_paths", lambda root: None)

    listing = inventory._list_top_level(workdir)

    assert "temp/" in listing
    assert "notes-scratch.md" in listing
    assert "image-uploads" in listing["data/"]


def test_markdown_files_tracked_only(workdir):
    tracked = inventory._tracked_paths(workdir)

    files = inventory._markdown_files(workdir, tracked)

    assert "docs/guide.md" in files
    assert "notes-scratch.md" not in files
    assert "temp/source/notes.md" not in files


def test_snapshot_stable_under_runtime_noise(workdir):
    options = inventory.InventoryOptions()
    before = inventory.build_inventory(workdir, options)
    (workdir / "data" / "image-uploads" / "new.jpg").write_text("x")
    (workdir / "another-scratch.md").write_text("x")

    after = inventory.build_inventory(workdir, options)

    assert before["top_level_inventory"] == after["top_level_inventory"]
    assert before["markdown_files"] == after["markdown_files"]


@pytest.mark.skipif(shutil.which("git") is None, reason="requires git")
def test_real_git_repo_excludes_untracked(tmp_path):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.test"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "test"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    (tmp_path / "keep.md").write_text("tracked", encoding="utf-8")
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "image-uploads").mkdir(parents=True)
    (tmp_path / "data" / "image-uploads" / "x.jpg").write_text("x")
    subprocess.run(["git", "add", "keep.md"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "-m", "init"], cwd=tmp_path, check=True, capture_output=True
    )

    listing = inventory._list_top_level(tmp_path)

    assert "keep.md" in listing
    assert "data/" not in listing
