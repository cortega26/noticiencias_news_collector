import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock

# Setup imports
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from news_collector.components.editorial.auditor import EditorialAuditor

# Configure logging
logging.basicConfig(level=logging.ERROR, format="%(name)s - %(message)s")
logger = logging.getLogger("AuditorRegressions")


class MockConfig:
    editorial_auditor = {"enabled": True}
    paths = {"data_dir": "./temp_auditor_regressions"}
    ollama = {"api_url": "http://mock", "model": "mock"}


def test_bool_generator_crash():
    """Reproduces 'bool object is not iterable' when provider returns bool instead of string/generator."""
    print("--- Test 1: Bool Generator Crash ---")
    config = MockConfig()
    auditor = EditorialAuditor(config)

    # Mock provider to return True
    auditor.provider.generate_sync = MagicMock(
        return_value=True
    )  # The 'True' from event.wait()

    try:
        # Trigger audit
        auditor.audit_article_sync("test_id", "content", "http://url")
        print("✅ Handled bool generator gracefully (logged error, no crash)")
    except TypeError as e:
        if "'bool' object is not iterable" in str(e):
            print(f"❌ Caught expected crash: {e}")
        else:
            print(f"❌ Caught unexpected crash: {e}")
    except Exception as e:
        print(f"❌ Caught unexpected exception: {type(e)} {e}")


def test_json_bool_crash():
    """Reproduces AttributeError if JSON extraction returns bool (e.g. 'true')."""
    print("\n--- Test 2: JSON Bool Crash ---")
    config = MockConfig()
    auditor = EditorialAuditor(config)

    # Mock provider to return 'true' string
    # generate_sync returns "true"
    # _extract_json("true") -> True
    # result.get() -> AttributeError
    auditor.provider.generate_sync = MagicMock(return_value="true")

    try:
        auditor.audit_article_sync("test_id_2", "content", "http://url")
        print("✅ Handled bool JSON result gracefully")
    except AttributeError as e:
        print(f"❌ Caught expected crash: {e}")
    except Exception as e:
        print(f"❌ Caught unexpected exception: {type(e)} {e}")


def test_true_string_crash():
    """Reproduces 'true' string response which might be parsed as bool, ensuring fail-open."""
    print("\n--- Test 3: 'true' String Crash ---")
    config = MockConfig()
    auditor = EditorialAuditor(config)

    # Mock provider to return "true" string
    # _extract_json("true") -> True (bool)
    # auditor should handle this as invalid (non-dict)
    auditor.provider.generate_sync = MagicMock(return_value="true")

    try:
        auditor.audit_article_sync("test_id_3", "content", "http://url")
        print("✅ Handled 'true' string gracefully (defaults used)")
    except Exception as e:
        print(f"❌ Caught unexpected exception: {type(e)} {e}")
        sys.exit(1)


def main():
    test_bool_generator_crash()
    test_json_bool_crash()
    test_true_string_crash()


if __name__ == "__main__":
    main()
