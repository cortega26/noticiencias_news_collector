"""Tests for scripts/mark_published.py exit-code semantics.

Verifies that the script reports failure (non-zero exit) when it finds posts
but marks none of them as published due to a real failure, while keeping the
happy path and dry-runs at exit 0.
"""

from __future__ import annotations

import sys

from scripts import mark_published

POST_BODY = """---
title: "Articulo de prueba"
source_url: "https://example.com/articulo"
permalink: "ciencia/articulo"
---

Cuerpo del articulo.
"""


def _write_post(tmp_path):
    posts_dir = tmp_path / "posts"
    posts_dir.mkdir()
    (posts_dir / "post.md").write_text(POST_BODY, encoding="utf-8")
    return posts_dir


class _FakeDBManager:
    """Stand-in for DatabaseManager; mark_article_published is configurable."""

    def __init__(self, *, result: bool):
        self._result = result

    def mark_article_published(self, *args, **kwargs):  # noqa: ANN002, ANN003
        return self._result


def test_main_returns_1_when_posts_found_but_none_marked(tmp_path, monkeypatch):
    posts_dir = _write_post(tmp_path)

    monkeypatch.setattr(
        mark_published,
        "DatabaseManager",
        lambda *a, **k: _FakeDBManager(result=False),
    )
    monkeypatch.setattr(sys, "argv", ["mark_published", "--posts-dir", str(posts_dir)])

    assert mark_published.main() == 1


def test_main_returns_0_on_happy_path(tmp_path, monkeypatch):
    posts_dir = _write_post(tmp_path)

    monkeypatch.setattr(
        mark_published,
        "DatabaseManager",
        lambda *a, **k: _FakeDBManager(result=True),
    )
    monkeypatch.setattr(sys, "argv", ["mark_published", "--posts-dir", str(posts_dir)])

    assert mark_published.main() == 0


def test_main_returns_0_on_dry_run(tmp_path, monkeypatch):
    posts_dir = _write_post(tmp_path)

    # In dry-run the DB is constructed but mark_article_published must never run.
    def _never_called(*a, **k):  # noqa: ANN002, ANN003
        raise AssertionError("mark_article_published must not run in dry-run")

    fake = _FakeDBManager(result=False)
    monkeypatch.setattr(fake, "mark_article_published", _never_called)
    monkeypatch.setattr(mark_published, "DatabaseManager", lambda *a, **k: fake)
    monkeypatch.setattr(
        sys,
        "argv",
        ["mark_published", "--posts-dir", str(posts_dir), "--dry-run"],
    )

    assert mark_published.main() == 0
