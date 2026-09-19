"""The publicly tunneled serving image must never run in the fail-open tier."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_serving_image_pins_production_environment():
    dockerfile = (ROOT / "Dockerfile.serving").read_text(encoding="utf-8")
    assert re.search(
        r"^ENV\s+NOTICIENCIAS__APP__ENVIRONMENT=production\s*$", dockerfile, re.M
    ), "Dockerfile.serving must pin NOTICIENCIAS__APP__ENVIRONMENT=production"


def test_admin_routes_fail_closed_in_the_image_environment():
    """Same env the image sets, no ADMIN_API_KEY: admin must answer 503, not 200.

    Runs in a fresh interpreter: the runtime config is cached per process, so an
    in-process env change would not be observed.
    """
    code = (
        "from fastapi.testclient import TestClient\n"
        "from news_collector.serving import create_app\n"
        "c = TestClient(create_app(), raise_server_exceptions=False)\n"
        "print(c.get('/v1/admin/analytics').status_code, c.get('/healthz').status_code)\n"
    )
    env = {k: v for k, v in os.environ.items() if k != "ADMIN_API_KEY"}
    env["NOTICIENCIAS__APP__ENVIRONMENT"] = "production"
    result = subprocess.run(  # noqa: S603 - fixed argv, test-only
        [sys.executable, "-c", code],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    )
    assert result.stdout.split()[-2:] == ["503", "200"], result.stdout + result.stderr
