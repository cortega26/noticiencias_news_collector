"""Plan 134: the serving image ships no ``apps/``, so nothing under
``news_collector/`` may import it.

``Dockerfile.serving`` copies only ``news_collector/``, ``noticiencias/`` and
``config.toml`` — no ``apps/`` — and ``pyproject.toml``'s ``packages.find``
excludes it too. The admin endpoints imported the published-content / analytics /
bulk helpers *inside* their handler bodies, so the legacy paths booted cleanly
(function-local imports) and only failed at request time with
``ModuleNotFoundError`` -> HTTP 500 in the deployed image, where the image's
``production`` tier plus an ``ADMIN_API_KEY`` make those routes reachable.
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Iterator, Tuple

ROOT = Path(__file__).resolve().parents[3]
PACKAGE_ROOT = ROOT / "news_collector"


def _imported_module_names(tree: ast.AST) -> Iterator[Tuple[int, str]]:
    """Yield ``(lineno, module)`` for every absolute import in ``tree``."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            yield node.lineno, node.module or ""


def test_no_news_collector_module_imports_the_legacy_apps_tree():
    """Any ``from apps.… import`` under news_collector/ 500s in the image.

    Function-local imports included: the image boot does not exercise them, so
    only a static scan (or a live request) can catch a regression here.
    """
    offenders = [
        f"{path.relative_to(ROOT)}:{lineno} ({module})"
        for path in sorted(PACKAGE_ROOT.rglob("*.py"))
        for lineno, module in _imported_module_names(
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        )
        if module == "apps" or module.startswith("apps.")
    ]
    assert offenders == [], (
        "news_collector/ must not import the legacy apps/ tree: Dockerfile.serving "
        "copies no apps/ and pyproject packages.find excludes it, so these imports "
        "would only fail at request time in the deployed image. Offenders: "
        + ", ".join(offenders)
    )


def test_admin_analytics_serves_from_a_tree_without_the_apps_directory(tmp_path):
    """Image-shaped tree (no ``apps/``): ``GET /v1/admin/analytics`` must answer 200.

    Fresh interpreter rooted in a directory holding only ``news_collector/``,
    ``noticiencias/`` and ``config.toml`` — exactly what the image COPYs — in the
    environment tier the image pins (``production`` + ``ADMIN_API_KEY``). Before
    plan 134 the handler's ``from apps.refinery.analytics_read_model import …``
    raised ModuleNotFoundError, i.e. HTTP 500 instead of this 200.
    """
    (tmp_path / "news_collector").symlink_to(
        ROOT / "news_collector", target_is_directory=True
    )
    (tmp_path / "noticiencias").symlink_to(
        ROOT / "noticiencias", target_is_directory=True
    )
    (tmp_path / "config.toml").symlink_to(ROOT / "config.toml")

    code = textwrap.dedent("""
        import importlib.util

        from fastapi.testclient import TestClient

        import news_collector.logic.workflows.published_content as published
        import news_collector.serving.analytics_read_model as analytics
        import news_collector.serving.bulk_helper as bulk
        from news_collector.serving import create_app

        assert importlib.util.find_spec("apps") is None, (
            "apps/ must not be importable from this tree"
        )

        client = TestClient(create_app(), raise_server_exceptions=False)
        response = client.get(
            "/v1/admin/analytics", headers={"Authorization": "Bearer test"}
        )
        assert response.status_code == 200, (response.status_code, response.text)

        # The three modules the admin handlers import at request time, resolvable
        # without the legacy tree on disk.
        assert analytics.build_analytics_read_model.__module__ == analytics.__name__
        assert bulk.run_bulk.__module__ == bulk.__name__
        assert (
            published.resolve_published_content_snapshot.__module__
            == published.__name__
        )
        print("SERVING-IMPORT-SURFACE-OK")
        """)
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    env["NOTICIENCIAS__APP__ENVIRONMENT"] = "production"
    env["ADMIN_API_KEY"] = "test"
    result = subprocess.run(  # noqa: S603 - fixed argv, test-only
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    assert "SERVING-IMPORT-SURFACE-OK" in result.stdout
