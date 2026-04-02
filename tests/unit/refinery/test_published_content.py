from __future__ import annotations

import shutil
from pathlib import Path
from types import SimpleNamespace

import git

import apps.refinery.main as refinery_main
from apps.refinery import published_content


def _init_repo(path: Path, remote_url: str) -> git.Repo:
    repo = git.Repo.init(path)
    repo.create_remote("origin", remote_url)
    return repo


def _write_post(posts_dir: Path, name: str, frontmatter: str, body: str = "Body") -> Path:
    posts_dir.mkdir(parents=True, exist_ok=True)
    file_path = posts_dir / name
    file_path.write_text(f"---\n{frontmatter}\n---\n\n{body}\n", encoding="utf-8")
    return file_path


def test_read_published_article_supports_numeric_and_string_refinery_ids(tmp_path: Path):
    numeric_post = _write_post(
        tmp_path,
        "2026-01-01-numeric.md",
        'title: "Numeric"\nrefinery_id: "123"',
    )
    string_post = _write_post(
        tmp_path,
        "2026-01-02-string.md",
        "title: String\nrefinery_id: A Massive Star Suddenly Vanished and Left a Black Hole Behind",
    )
    missing_id_post = _write_post(
        tmp_path,
        "2026-01-03-missing.md",
        'title: "Missing"',
    )

    numeric_record = published_content.read_published_article(numeric_post)
    string_record = published_content.read_published_article(string_post)
    missing_id_record = published_content.read_published_article(missing_id_post)

    assert numeric_record.refinery_id == "123"
    assert string_record.refinery_id == (
        "A Massive Star Suddenly Vanished and Left a Black Hole Behind"
    )
    assert missing_id_record.refinery_id is None


def test_parse_frontmatter_text_ignores_body_content(tmp_path: Path):
    article = _write_post(
        tmp_path,
        "2026-02-16-black-hole.md",
        "title: Stable metadata\nrefinery_id: visible-id",
        body=(
            "Paragraph.\n\n"
            "refinery_id: this value belongs to the body and must not leak into the UI.\n"
        ),
    )

    parsed = published_content.parse_frontmatter_file(article)
    record = published_content.read_published_article(article)

    assert parsed["refinery_id"] == "visible-id"
    assert record.refinery_id == "visible-id"


def test_resolve_published_content_snapshot_prefers_verified_local_checkout(
    tmp_path: Path,
):
    collector_repo_root = tmp_path / "collector"
    collector_repo_root.mkdir()

    frontend_repo = tmp_path / "noticiencias"
    _init_repo(frontend_repo, "https://github.com/cortega26/noticiencias.git")
    frontend_posts = frontend_repo / "src/content/posts"
    _write_post(frontend_posts, "2026-03-27-live.md", 'title: "Frontend"\nrefinery_id: "27"')
    _write_post(frontend_posts, "2026-03-26-live.md", 'title: "Frontend 2"\nrefinery_id: "26"')

    clone_repo = tmp_path / "temp-target"
    _init_repo(clone_repo, "https://github.com/cortega26/noticiencias.git")
    clone_posts = clone_repo / "src/content/posts"
    _write_post(clone_posts, "2026-02-18-stale.md", 'title: "Stale"\nrefinery_id: "849"')

    snapshot = published_content.resolve_published_content_snapshot(
        target_repo_url="https://github.com/cortega26/noticiencias.git",
        collector_repo_root=collector_repo_root,
        temp_target_dir=clone_repo,
        refresh_clone=False,
    )

    assert snapshot.source_label == "Checkout local verificado del frontend"
    assert snapshot.repo_root == frontend_repo.resolve()
    assert len(snapshot.articles) == 2


def test_resolve_published_content_snapshot_refreshes_clone_when_no_local_checkout(
    tmp_path: Path, monkeypatch
):
    collector_repo_root = tmp_path / "collector"
    collector_repo_root.mkdir()
    temp_target_dir = tmp_path / "temp-target"

    def fake_refresh(*, target_repo_url: str, target_dir: Path, github_token: str = ""):
        _init_repo(target_dir, target_repo_url)
        _write_post(
            target_dir / "src/content/posts",
            "2026-02-18-article-849.md",
            'title: "Durable storage"\nrefinery_id: "849"',
        )
        return target_dir, "Clon temporal actualizado desde origin"

    monkeypatch.setattr(
        published_content, "refresh_published_target_clone", fake_refresh
    )

    snapshot = published_content.resolve_published_content_snapshot(
        target_repo_url="https://github.com/cortega26/noticiencias.git",
        collector_repo_root=collector_repo_root,
        temp_target_dir=temp_target_dir,
        refresh_clone=True,
        extra_candidates=[collector_repo_root],
    )

    assert snapshot.source_label == "Clon temporal actualizado desde origin"
    assert snapshot.repo_root == temp_target_dir.resolve()
    assert len(snapshot.articles) == 1


def test_delete_article_supports_legacy_string_refinery_id(
    tmp_path: Path, monkeypatch
):
    prepared_repo = tmp_path / "prepared-target"
    _init_repo(prepared_repo, "https://github.com/cortega26/noticiencias.git")
    _write_post(
        prepared_repo / "src/content/posts",
        "2026-02-16-un-agujero-negro-se-forma-sin-explotar-una-estrella-masiva.md",
        (
            "title: Un agujero negro se forma sin explotar una estrella masiva\n"
            "refinery_id: A Massive Star Suddenly Vanished and Left a Black Hole Behind"
        ),
    )

    target_clone = tmp_path / "runtime-target"

    class FakeGitHubPublisher:
        def __init__(self, _token: str):
            return None

        def clone_repo(self, _repo_url: str, target_dir: Path):
            shutil.copytree(prepared_repo, target_dir)
            return git.Repo(target_dir)

        def create_branch(self, _repo, branch_prefix: str = "delete/article", **_kwargs):
            return f"{branch_prefix}-legacy-id"

        def commit_and_push(self, _repo, _message: str, _branch_name: str):
            return None

        def create_pull_request(
            self,
            *,
            repo_url: str,
            branch_name: str,
            title: str,
            body: str,
        ) -> str:
            assert repo_url == "https://github.com/cortega26/noticiencias.git"
            assert branch_name == "delete/article-legacy-id"
            assert "Refinery ID: A Massive Star Suddenly Vanished and Left a Black Hole Behind" in body
            return "https://github.com/cortega26/noticiencias/pull/1"

    config = SimpleNamespace(
        github=SimpleNamespace(
            token="",
            target_repo_url="https://github.com/cortega26/noticiencias.git",
        )
    )

    monkeypatch.setattr(refinery_main, "load_config", lambda: config)
    monkeypatch.setattr(refinery_main, "GitHubPublisher", FakeGitHubPublisher)
    monkeypatch.setattr(refinery_main, "TARGET_DIR", target_clone)

    result = refinery_main.delete_article(
        "A Massive Star Suddenly Vanished and Left a Black Hole Behind"
    )

    assert result["status"] == "success"
    assert result["file_name"] == (
        "2026-02-16-un-agujero-negro-se-forma-sin-explotar-una-estrella-masiva.md"
    )
