import json
from pathlib import Path
from unittest.mock import MagicMock

from news_collector.logic.workflows.refinery_engine import (
    MANIFEST_FILENAME,
    RefineryEngine,
)


def test_manifest_operations(tmp_path):
    """Verify manifest loading, lookup, and updates."""

    # Setup
    mock_db = MagicMock()
    mock_git = MagicMock()
    mock_editor = MagicMock()
    mock_config = MagicMock()
    mock_config.app.policy_integrity_mode = "disabled"

    engine = RefineryEngine(mock_db, mock_git, mock_editor, mock_config)

    # 1. Test Empty Load
    engine._load_manifest(tmp_path)
    assert engine._manifest_cache == {}

    # 2. Test Update & Persist
    article_id = "123"
    filename = "2024-01-01-article.md"
    engine._update_manifest(tmp_path, article_id, filename)

    manifest_file = tmp_path / MANIFEST_FILENAME
    assert manifest_file.exists()
    data = json.loads(manifest_file.read_text())
    assert data[article_id] == filename

    # 3. Test Lookup (Cache Hit)
    # Create the dummy file so _find_existing_file says it exists
    (tmp_path / filename).touch()

    found_path = engine._find_existing_file(tmp_path, article_id)
    assert found_path == tmp_path / filename

    # 4. Test Stale Entry (Cache Miss fallback)
    # Delete the file but keep it in manifest
    (tmp_path / filename).unlink()

    # Should log warning and return None (since scan won't find it either)
    found_path = engine._find_existing_file(tmp_path, article_id)
    assert found_path is None


def test_manifest_write_atomic(tmp_path):
    """B-05 / F-0025: Manifest write uses tmp+rename so it's always valid JSON."""

    mock_db = MagicMock()
    mock_git = MagicMock()
    mock_editor = MagicMock()
    mock_config = MagicMock()
    mock_config.app.policy_integrity_mode = "disabled"

    engine = RefineryEngine(mock_db, mock_git, mock_editor, mock_config)

    # Write several entries
    for i in range(5):
        engine._update_manifest(tmp_path, str(i), f"2024-01-0{i+1}-article-{i}.md")

    manifest_file = tmp_path / MANIFEST_FILENAME
    assert manifest_file.exists(), "Manifest file should exist after updates"

    # Verify the file is valid JSON with all entries
    data = json.loads(manifest_file.read_text(encoding="utf-8"))
    assert len(data) == 5
    for i in range(5):
        assert data[str(i)] == f"2024-01-0{i+1}-article-{i}.md"

    # Verify no .tmp file left behind (atomic rename should clean up)
    tmp_file = tmp_path / (MANIFEST_FILENAME.replace(".json", ".tmp"))
    assert not tmp_file.exists(), ".tmp file should not remain after atomic write"


if __name__ == "__main__":
    try:
        # Minimal runner
        import shutil

        test_dir = Path("tests/temp_manifest_test")
        if test_dir.exists():
            shutil.rmtree(test_dir)
        test_dir.mkdir()

        test_manifest_operations(test_dir)
        print("✅ Refinery Manifest Test Passed")

        shutil.rmtree(test_dir)
    except Exception as e:
        print(f"❌ Refinery Manifest Test Failed: {e}")
        exit(1)
