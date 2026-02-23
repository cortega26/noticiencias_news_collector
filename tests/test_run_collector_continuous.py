from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

SCRIPT_PATH = (
    Path(__file__).resolve().parents[1] / "scripts" / "run_collector_continuous.py"
)
SPEC = importlib.util.spec_from_file_location("run_collector_continuous", SCRIPT_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_smoke_mode_runs_single_cycle_without_sleep() -> None:
    env = {"NOTICIENCIAS_SMOKE": "1", "COLLECTION_INTERVAL_SECONDS": "600"}
    with patch.dict(MODULE.os.environ, env, clear=False):
        with patch.object(
            MODULE.subprocess, "run", return_value=SimpleNamespace(returncode=0)
        ) as mock_run:
            with patch.object(MODULE.time, "sleep") as mock_sleep:
                exit_code = MODULE.main()

    assert exit_code == 0
    mock_run.assert_called_once_with(
        [MODULE.sys.executable, "scripts/run_collector_smoke.py"],
        capture_output=False,
        check=False,
    )
    mock_sleep.assert_not_called()


def test_continuous_mode_still_sleeps_between_cycles() -> None:
    env = {"NOTICIENCIAS_SMOKE": "0", "COLLECTION_INTERVAL_SECONDS": "7"}
    with patch.dict(MODULE.os.environ, env, clear=False):
        with patch.object(
            MODULE.subprocess, "run", return_value=SimpleNamespace(returncode=0)
        ):
            with patch.object(MODULE.time, "sleep", side_effect=RuntimeError("stop")):
                with pytest.raises(RuntimeError, match="stop"):
                    MODULE.main()
