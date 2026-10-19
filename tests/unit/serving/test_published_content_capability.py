"""Plan 151: published content is a local-admin capability, reported as 503.

``GET /v1/admin/content``, ``DELETE /v1/admin/content/{refinery_id}`` and
``POST /v1/admin/content/bulk-reset`` read the frontend repository through
GitPython, and ``Dockerfile.serving`` ships neither a ``git`` binary nor a
frontend checkout. Those routes must answer 503 with a stable
``error_code=published_content_unavailable`` — never the ``ImportError`` 500
the deployed image used to show — while the local stack (git plus a checkout,
or the clone the module already makes on demand) keeps working unchanged.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path
from unittest.mock import patch

import git
import pytest
from fastapi.testclient import TestClient

import news_collector.logic.workflows.published_content as published_content
from news_collector.serving import api as serving_api
from news_collector.serving import create_app
from news_collector.storage.database import DatabaseManager

ROOT = Path(__file__).resolve().parents[3]
FRONTEND_REPO_URL = "https://github.com/example/noticiencias.git"
ADMIN_TOKEN = "dev-admin-token"


def _admin_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {ADMIN_TOKEN}"}


def _make_frontend_checkout(path: Path) -> Path:
    """A minimal working tree the module's own resolution accepts as target."""
    repo = git.Repo.init(path)
    repo.create_remote("origin", FRONTEND_REPO_URL)
    (path / "src" / "content" / "posts").mkdir(parents=True)
    return path


def _probe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **overrides):
    """Run the capability probe with git reported as present on PATH."""
    monkeypatch.setattr(serving_api.shutil, "which", lambda name: "/usr/bin/git")
    kwargs = {
        "target_repo_url": "",
        "collector_repo_root": tmp_path / "collector",
        "temp_target_dir": tmp_path / "temp-target",
    }
    kwargs.update(overrides)
    return serving_api._published_content_missing_requirement(**kwargs)


# ---------------------------------------------------------------------------
# The probe itself
# ---------------------------------------------------------------------------


def test_probe_reports_a_missing_git_binary(tmp_path, monkeypatch):
    monkeypatch.setattr(serving_api.shutil, "which", lambda name: None)
    missing = serving_api._published_content_missing_requirement(
        target_repo_url=FRONTEND_REPO_URL,
        collector_repo_root=tmp_path / "collector",
        temp_target_dir=tmp_path / "temp-target",
    )
    assert missing == "a git executable"


def test_probe_accepts_a_local_frontend_checkout(tmp_path, monkeypatch):
    """git + a resolvable checkout is the fully-provisioned local stack."""
    checkout = _make_frontend_checkout(tmp_path / "noticiencias")
    real_find = published_content.find_local_target_checkout
    resolved: list = []

    def _recording_find(target_repo_url, **kwargs):
        found = real_find(target_repo_url, **kwargs)
        resolved.append(found)
        return found

    # The probe must borrow the module's own resolution, not re-implement it.
    monkeypatch.setattr(
        published_content, "find_local_target_checkout", _recording_find
    )
    missing = _probe(
        tmp_path,
        monkeypatch,
        target_repo_url=FRONTEND_REPO_URL,
        extra_candidates=[checkout],
    )
    assert resolved and resolved[0] == checkout.resolve()
    assert missing is None


def test_probe_treats_on_demand_clone_as_available(tmp_path, monkeypatch):
    """A missing checkout is not a missing capability (STOP condition).

    With a git binary and a configured target repository the module clones on
    demand; answering 503 here would break the documented local flow.
    """
    assert _probe(tmp_path, monkeypatch, target_repo_url=FRONTEND_REPO_URL) is None


def test_probe_accepts_an_existing_temp_clone(tmp_path, monkeypatch):
    monkeypatch.setattr(
        published_content, "find_local_target_checkout", lambda *a, **k: None
    )
    temp_target = tmp_path / "temp-target"
    (temp_target / "src" / "content" / "posts").mkdir(parents=True)
    assert _probe(tmp_path, monkeypatch, temp_target_dir=temp_target) is None


def test_probe_reports_an_unconfigured_frontend(tmp_path, monkeypatch):
    """Nothing readable anywhere and nothing configured to clone."""
    monkeypatch.setattr(
        published_content, "find_local_target_checkout", lambda *a, **k: None
    )
    assert _probe(tmp_path, monkeypatch) == "a configured frontend repository"


def test_probe_reports_a_broken_git_installation(tmp_path, monkeypatch):
    """git on PATH but GitPython cannot initialise it -> still a capability."""
    monkeypatch.setattr(serving_api.shutil, "which", lambda name: "/usr/bin/git")
    monkeypatch.setitem(
        sys.modules, "news_collector.logic.workflows.published_content", None
    )
    missing = serving_api._published_content_missing_requirement(
        target_repo_url=FRONTEND_REPO_URL,
        collector_repo_root=tmp_path / "collector",
        temp_target_dir=tmp_path / "temp-target",
    )
    assert missing == "a working git installation"


# ---------------------------------------------------------------------------
# The three routes
# ---------------------------------------------------------------------------


@pytest.fixture()
def api_client(tmp_path: Path):
    manager = DatabaseManager({"type": "sqlite", "path": tmp_path / "plan151.db"})
    try:
        yield TestClient(
            create_app(database_manager=manager), raise_server_exceptions=False
        )
    finally:
        manager.close()


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("get", "/v1/admin/content", None),
        ("delete", "/v1/admin/content/2026-01-01-x", None),
        (
            "post",
            "/v1/admin/content/bulk-reset",
            {"refinery_ids": ["2026-01-01-x"]},
        ),
    ],
)
def test_published_content_routes_report_the_capability_as_503(
    api_client: TestClient, monkeypatch, method: str, path: str, payload
):
    monkeypatch.setattr(
        serving_api,
        "_published_content_missing_requirement",
        lambda **kwargs: "a git executable",
    )
    with patch.dict(os.environ, {"ADMIN_API_KEY": ADMIN_TOKEN}):
        request_kwargs = {"headers": _admin_headers()}
        if payload is not None:
            request_kwargs["json"] = payload
        response = getattr(api_client, method)(path, **request_kwargs)

    assert response.status_code == 503, response.text
    body = response.json()
    assert body["error_code"] == "published_content_unavailable"
    assert "local admin stack" in body["detail"]
    # Names the requirement without leaking internal paths or tracebacks.
    assert "git" in body["detail"]
    assert "traceback" not in body["detail"].lower()
    assert "/" not in body["detail"]


def test_import_failure_never_surfaces_as_a_500(api_client: TestClient, monkeypatch):
    """Defence in depth: the probe says "available" and the import still fails."""
    monkeypatch.setattr(
        serving_api, "_published_content_missing_requirement", lambda **kwargs: None
    )
    monkeypatch.setitem(
        sys.modules, "news_collector.logic.workflows.published_content", None
    )
    with patch.dict(os.environ, {"ADMIN_API_KEY": ADMIN_TOKEN}):
        response = api_client.get("/v1/admin/content", headers=_admin_headers())

    assert response.status_code == 503, response.text
    assert response.json()["error_code"] == "published_content_unavailable"


def test_image_shaped_tree_without_git_answers_503(tmp_path: Path):
    """The deployed-image condition, in-process: no git binary anywhere.

    Same image-shaped tree as the plan-134 import-surface test (only
    ``news_collector/``, ``noticiencias/`` and ``config.toml``), in the tier
    ``Dockerfile.serving`` pins, but with ``PATH`` pointing at an empty
    directory — exactly what the container has. ``/healthz`` must keep
    answering 200; the published-content route must say why it cannot work.
    """
    (tmp_path / "news_collector").symlink_to(
        ROOT / "news_collector", target_is_directory=True
    )
    (tmp_path / "noticiencias").symlink_to(
        ROOT / "noticiencias", target_is_directory=True
    )
    (tmp_path / "config.toml").symlink_to(ROOT / "config.toml")
    empty_bin = tmp_path / "empty-bin"
    empty_bin.mkdir()

    code = textwrap.dedent("""
        import shutil

        from fastapi.testclient import TestClient

        from news_collector.serving import create_app

        assert shutil.which("git") is None, "test setup: git must be invisible"
        client = TestClient(create_app(), raise_server_exceptions=False)
        health = client.get("/healthz")
        assert health.status_code == 200, (health.status_code, health.text)
        content = client.get(
            "/v1/admin/content", headers={"Authorization": "Bearer test"}
        )
        body = content.json()
        assert content.status_code == 503, (content.status_code, content.text)
        assert body["error_code"] == "published_content_unavailable", body
        assert "local admin stack" in body["detail"], body
        print("PUBLISHED-CONTENT-503-OK")
        """)
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in ("PYTHONPATH", "GIT_PYTHON_GIT_EXECUTABLE")
    }
    env["NOTICIENCIAS__APP__ENVIRONMENT"] = "production"
    env["ADMIN_API_KEY"] = "test"
    env["PATH"] = str(empty_bin)
    result = subprocess.run(  # noqa: S603 - fixed argv, test-only
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    assert "PUBLISHED-CONTENT-503-OK" in result.stdout
