
import subprocess
import sys
import json
import pytest
from unittest.mock import patch, MagicMock
from news_collector.exceptions import (
    NewsCollectorError,
    ConfigError,
    IngestionError,
    SourceUnavailableError,
    ContractError,
    OperationalError,
    OperationalIOError,
    EXIT_CONFIG,
    EXIT_INGESTION,
    EXIT_CONTRACT,
    EXIT_OPERATIONAL,
    EXIT_INTERNAL,
)
import main

# Unit Tests for handle_exception
# -------------------------------

def test_handle_exception_exit_code():
    """Verify handle_exception exits with correct code for known exceptions."""
    # Test ConfigError -> 3
    with pytest.raises(SystemExit) as pytest_wrapped_e:
        main.handle_exception(ConfigError("Config failed"))
    assert pytest_wrapped_e.type == SystemExit
    assert pytest_wrapped_e.value.code == EXIT_CONFIG

    # Test IngestionError -> 4
    with pytest.raises(SystemExit) as pytest_wrapped_e:
        main.handle_exception(IngestionError("Download failed"))
    assert pytest_wrapped_e.type == SystemExit
    assert pytest_wrapped_e.value.code == EXIT_INGESTION
    
    # Test OperationalError -> 6
    with pytest.raises(SystemExit) as pytest_wrapped_e:
        main.handle_exception(OperationalError("DB down"))
    assert pytest_wrapped_e.type == SystemExit
    assert pytest_wrapped_e.value.code == EXIT_OPERATIONAL

    # Test Generic Exception -> 10
    with pytest.raises(SystemExit) as pytest_wrapped_e:
        main.handle_exception(ValueError("Unknown error"))
    assert pytest_wrapped_e.type == SystemExit
    assert pytest_wrapped_e.value.code == EXIT_INTERNAL

def test_handle_exception_output(capsys):
    """Verify handle_exception produces correct JSON and stderr output."""
    error_msg = "Test error message"
    with pytest.raises(SystemExit):
        main.handle_exception(IngestionError(error_msg))
    
    captured = capsys.readouterr()
    
    # Check stdout is valid JSON
    try:
        log_data = json.loads(captured.out)
        assert log_data["status"] == "fatal_error"
        assert log_data["error_message"] == error_msg
        assert log_data["exit_code"] == EXIT_INGESTION
        assert log_data["error_category"] == "INGESTION_ERROR"
    except json.JSONDecodeError:
        pytest.fail("Output to stdout was not valid JSON")

    # Check stderr contains human readable message
    assert "❌ ERROR FATAL DEL SISTEMA" in captured.err
    assert f"(Código {EXIT_INGESTION})" in captured.err
    assert "Categoría: INGESTION_ERROR" in captured.err
    assert error_msg in captured.err

# Integration Tests via Subprocess
# --------------------------------

def test_main_help_exit_code():
    """Verify main.py --help exits with 0."""
    result = subprocess.run(
        [sys.executable, "main.py", "--help"],
        capture_output=True,
        text=True
    )
    assert result.returncode == 0
    assert "usage: main.py" in result.stdout

def test_main_invalid_arg_exit_code():
    """Verify main.py --invalid exits with 2 (argparse default)."""
    result = subprocess.run(
        [sys.executable, "main.py", "--invalid-arg"],
        capture_output=True,
        text=True
    )
    assert result.returncode == 2




def test_main_mocked_exception_flow():
    """
    Mock create_system to raise a specific error and verify main exits correctly.
    This simulates a runtime error bubbling up to the global handler.
    """
    # Patch the object where it is used in main.py
    with patch("main.create_system") as mock_create:
        mock_create.side_effect = OperationalIOError("Database connection failed")
        
        # We also need to patch sys.argv
        with patch.object(sys, 'argv', ["main.py", "--dry-run"]):
             with pytest.raises(SystemExit) as pytest_wrapped_e:
                 main.main()
             
             assert pytest_wrapped_e.value.code == EXIT_OPERATIONAL

