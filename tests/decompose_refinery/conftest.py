"""
Shared fixtures and helpers for the decompose_refinery test suite.

These tests verify the behaviour of the four focused collaborators extracted from
RefineryEngine. They are written BEFORE the implementation so that each collaborator
can be built against a known contract (TDD). Running this suite against the current
codebase will produce ImportError or AttributeError for the new modules — that is
expected and normal until each phase of the decomposition is complete.

Tests in this suite must NOT require a running database, network, or filesystem beyond
tmp_path. All external I/O is mocked at the boundary.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Shared article payload factory
# ---------------------------------------------------------------------------

def make_article(
    *,
    article_id: str = "42",
    title: str = "Test Article Title",
    url: str = "https://example.com/article",
    summary: str = "A sufficiently long summary for validation purposes.",
    image_url: str = "https://example.com/image.jpg",
    published_date: datetime | None = None,
    collected_date: datetime | None = None,
    source_id: str = "src",
    source_name: str = "Source Name",
    category: str = "science",
    **extra: Any,
) -> dict:
    payload = {
        "id": article_id,
        "title": title,
        "url": url,
        "summary": summary,
        "image_url": image_url,
        "source_id": source_id,
        "source_name": source_name,
        "category": category,
        "source_metadata": {},
    }
    if published_date is not None:
        payload["published_date"] = published_date
    if collected_date is not None:
        payload["collected_date"] = collected_date
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# Config factory that matches the shape expected by all collaborators
# ---------------------------------------------------------------------------

def make_config(*, target_repo_url: str = "https://github.com/org/repo") -> SimpleNamespace:
    return SimpleNamespace(
        app=SimpleNamespace(
            policy_integrity_mode="disabled",
            editorial_mode="standard",
        ),
        paths=SimpleNamespace(data_dir="/tmp/refinery_test_data"),
        github=SimpleNamespace(target_repo_url=target_repo_url),
    )


# ---------------------------------------------------------------------------
# Fake mock DB
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_db() -> MagicMock:
    db = MagicMock()
    db.get_canonical_slug.return_value = None
    db.set_canonical_slug.return_value = True
    db.get_publishing_state.return_value = None
    db.mark_article_published.return_value = None
    db.mark_article_publishing.return_value = None
    return db


# ---------------------------------------------------------------------------
# Fake mock git handler
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_git() -> MagicMock:
    git = MagicMock()
    git.create_branch.return_value = "content/update-2024-01-25-test-article"
    git.commit_and_push.return_value = None
    git.create_pull_request.return_value = "https://github.com/org/repo/pull/1"
    return git
