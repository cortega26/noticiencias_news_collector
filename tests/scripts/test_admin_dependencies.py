"""Admin launchers must reject incomplete/stale installations before booting."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture()
def admin_repo(tmp_path: Path) -> Path:
    if shutil.which("npm") is None:
        pytest.skip("npm is required for the offline admin startup regression")
    root = tmp_path / "repo with spaces"
    app = root / "apps" / "admin"
    app.mkdir(parents=True)
    (root / "scripts" / "dev").mkdir(parents=True)
    (root / ".venv" / "bin").mkdir(parents=True)
    (root / ".venv" / "bin" / "python").symlink_to(shutil.which("true") or "/bin/true")
    for name in ("admin_stack.sh", "check_admin_dependencies.sh"):
        source = REPO_ROOT / "scripts" / "dev" / name
        if source.exists():
            shutil.copy2(source, root / "scripts" / "dev" / name)
    shutil.copy2(REPO_ROOT / "Makefile", root / "Makefile")
    (app / "package.json").write_text(
        json.dumps(
            {
                "name": "admin-startup-fixture",
                "version": "1.0.0",
                "dependencies": {"openapi-fetch": "0.17.0"},
                "devDependencies": {"typescript": "5.9.3"},
                "scripts": {
                    "dev": "node -e \"require('fs').writeFileSync('gui-started', '')\" --"
                },
            }
        ),
        encoding="utf-8",
    )
    return root


def install_fixture_package(root: Path, name: str, version: str) -> None:
    package = root / "apps" / "admin" / "node_modules" / name
    package.mkdir(parents=True)
    (package / "package.json").write_text(
        json.dumps({"name": name, "version": version}), encoding="utf-8"
    )


def run_command(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=root,
        env={
            **os.environ,
            "PYTHON_BIN": shutil.which("true") or "/bin/true",
            "API_PORT": "invalid",
            "NODE_ENV": "production",  # Dev tools must still be checked.
            "npm_config_offline": "true",
            "npm_config_cache": str(root / "npm-cache"),
        },
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


@pytest.mark.parametrize(
    "state", ["absent", "incomplete", "incompatible", "missing-dev"]
)
def test_preflight_rejects_unusable_tree(admin_repo: Path, state: str) -> None:
    if state != "absent":
        (admin_repo / "apps/admin/node_modules").mkdir()
    if state in {"incompatible", "missing-dev"}:
        version = "0.16.0" if state == "incompatible" else "0.17.0"
        install_fixture_package(admin_repo, "openapi-fetch", version)
    if state == "incompatible":
        install_fixture_package(admin_repo, "typescript", "5.9.3")

    result = run_command(admin_repo, "bash", "scripts/dev/check_admin_dependencies.sh")

    assert result.returncode != 0
    assert "make admin-install" in result.stderr
    assert not (admin_repo / "apps/admin/gui-started").exists()


def test_preflight_accepts_valid_tree_without_installing(admin_repo: Path) -> None:
    install_fixture_package(admin_repo, "openapi-fetch", "0.17.0")
    install_fixture_package(admin_repo, "typescript", "5.9.3")
    sentinel = admin_repo / "apps/admin/node_modules/keep"
    sentinel.write_text("preserve", encoding="utf-8")

    result = run_command(admin_repo, "bash", "scripts/dev/check_admin_dependencies.sh")

    assert result.returncode == 0, result.stderr
    assert sentinel.read_text(encoding="utf-8") == "preserve"
    assert not (admin_repo / "apps/admin/package-lock.json").exists()


@pytest.mark.parametrize("target", ["admin", "admin-dev"])
def test_launchers_reject_stale_tree_before_starting_services(
    admin_repo: Path, target: str
) -> None:
    (admin_repo / "apps/admin/node_modules").mkdir()

    result = run_command(admin_repo, "make", target)

    assert result.returncode != 0
    assert "make admin-install" in result.stderr
    assert "starting serving API" not in result.stdout
    assert "API_PORT=" not in result.stderr
    assert not (admin_repo / "apps/admin/gui-started").exists()


def test_gui_launcher_starts_with_valid_dependencies(admin_repo: Path) -> None:
    install_fixture_package(admin_repo, "openapi-fetch", "0.17.0")
    install_fixture_package(admin_repo, "typescript", "5.9.3")

    result = run_command(admin_repo, "make", "admin-dev", "API_PORT=1")

    assert result.returncode == 0, result.stderr
    assert (admin_repo / "apps/admin/gui-started").exists()
