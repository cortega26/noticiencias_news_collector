"""Workflows that execute repository code must not inherit default token scope.

Plan 142: ``source_reliability.yml``, ``system-verification.yml``, and
``mutation.yml`` ran without a ``permissions:`` block, so they inherited the
repository default token scope. This test pins the read-only declaration (and
that no job re-widens it) so a later workflow edit cannot silently drop it.
"""

from __future__ import annotations

from pathlib import Path

import yaml

WORKFLOWS_DIR = Path(__file__).resolve().parents[1] / ".github" / "workflows"

HARDENED_WORKFLOWS = (
    "source_reliability.yml",
    "system-verification.yml",
    "mutation.yml",
)


def test_hardened_workflows_declare_read_only_permissions():
    for name in HARDENED_WORKFLOWS:
        workflow = yaml.safe_load((WORKFLOWS_DIR / name).read_text(encoding="utf-8"))
        assert workflow.get("permissions") == {"contents": "read"}, name

        for job_name, job in workflow.get("jobs", {}).items():
            assert "permissions" not in job, f"{name} job {job_name} re-widens scope"
