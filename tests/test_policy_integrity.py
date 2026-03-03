import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from news_collector.editorial.policy import EditorialPolicy, IntegrityError
from news_collector.logic.workflows.refinery_engine import RefineryEngine


class TestPolicyIntegrity:

    @pytest.fixture
    def mock_components(self):
        db = MagicMock()
        db.get_canonical_slug.return_value = None
        git = MagicMock()
        editor = MagicMock()
        config = MagicMock()
        config.app.editorial_mode = "standard"
        config.app.policy_integrity_mode = "enforced"
        return db, git, editor, config

    def test_startup_fails_on_integrity_error(self, mock_components):
        """Test 1: Engine refuses to start if Verify Integrity raises Error"""
        db, git, editor, config = mock_components

        # We need to patch EditorialPolicy.verify_integrity to raise IntegrityError
        with patch.object(
            EditorialPolicy,
            "verify_integrity",
            side_effect=IntegrityError("Hash Mismatch"),
        ):
            with pytest.raises(IntegrityError):
                with patch(
                    "news_collector.logic.workflows.refinery_engine.EditorialAuditor"
                ):
                    RefineryEngine(db, git, editor, config)

    def test_startup_succeeds_on_integrity_pass(self, mock_components):
        """Test 1b: Engine starts if Verify Integrity passes"""
        db, git, editor, config = mock_components

        with patch.object(EditorialPolicy, "verify_integrity", return_value=None):
            with patch(
                "news_collector.logic.workflows.refinery_engine.EditorialAuditor"
            ):
                engine = RefineryEngine(db, git, editor, config)
                assert engine.policy.mode == "standard"

    def test_audit_log_creation_blocked(self, mock_components):
        """Test 2: Blocked decision writes to audit log"""
        db, git, editor, config = mock_components

        with tempfile.TemporaryDirectory() as tmpdir:
            # Mock config.paths to return a dict-like object or be a dict
            # In RefineryEngine:
            # paths = getattr(config, "paths", None) or {}
            # if isinstance(paths, dict): ... else: ...

            # If config is MagicMock, getattr(config, "paths") is a MagicMock.
            # We need to make it behave like an object with data_dir attr OR a dict.
            # Easiest: Make it a simple object
            class PathsCfg:
                data_dir = tmpdir

            config.paths = PathsCfg()

            with patch.object(EditorialPolicy, "verify_integrity", return_value=None):
                with patch(
                    "news_collector.logic.workflows.refinery_engine.EditorialAuditor"
                ):
                    engine = RefineryEngine(db, git, editor, config)

            # Simulate Enforcement
            score = {"epistemic_rigor_score": 5.0}  # Fail
            engine._enforce_editorial_policy("test_audit_blocked", score)

            # Check Log
            log_path = Path(tmpdir) / "runtime" / "editorial_policy_enforcement_log.jsonl"
            assert log_path.exists()

            content = log_path.read_text()
            entry = json.loads(content.strip())

            assert entry["result"] == "blocked"
            assert entry["article_id"] == "test_audit_blocked"
            assert "Auditor Score" in entry["reason"]
            assert "policy_sha256" in entry

    def test_audit_log_creation_allowed(self, mock_components):
        """Test 3: Allowed decision writes to audit log"""
        db, git, editor, config = mock_components

        with tempfile.TemporaryDirectory() as tmpdir:

            class PathsCfg:
                data_dir = tmpdir

            config.paths = PathsCfg()

            with patch.object(EditorialPolicy, "verify_integrity", return_value=None):
                with patch(
                    "news_collector.logic.workflows.refinery_engine.EditorialAuditor"
                ):
                    engine = RefineryEngine(db, git, editor, config)

            # Simulate Enforcement
            score = {"epistemic_rigor_score": 9.0, "has_proper_caveats": True}
            engine._enforce_editorial_policy("test_audit_allowed", score)

            # Check Log
            log_path = Path(tmpdir) / "runtime" / "editorial_policy_enforcement_log.jsonl"
            content = log_path.read_text()
            entry = json.loads(content.strip())

            assert entry["result"] == "allowed"
            assert entry["article_id"] == "test_audit_allowed"
