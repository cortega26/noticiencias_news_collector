from unittest.mock import MagicMock, patch

import pytest
from news_collector.editorial.policy import EditorialPolicy
from news_collector.logic.workflows.refinery_engine import RefineryEngine


class TestEditorialPolicyEnforcement:

    @pytest.fixture
    def mock_components(self):
        db = MagicMock()
        db.get_canonical_slug.return_value = None  # Default: No slug in DB
        git = MagicMock()
        editor = MagicMock()
        config = MagicMock()
        config.app.editorial_mode = "standard"
        return db, git, editor, config

    @pytest.fixture
    def engine(self, mock_components):
        db, git, editor, config = mock_components

        # Patch the class inside the module where it is used
        with patch(
            "news_collector.logic.workflows.refinery_engine.EditorialAuditor"
        ) as MockAuditorClass:
            # Setup the instance returned by the class
            mock_auditor_instance = MockAuditorClass.return_value

            # Patch Integrity Check for these tests
            with patch.object(EditorialPolicy, "verify_integrity", return_value=None):
                engine = RefineryEngine(db, git, editor, config)

            # Verify usage
            assert engine.auditor == mock_auditor_instance

            # Other mocks
            engine.git = MagicMock()
            engine.writer.write_article = MagicMock(return_value=MagicMock())
            engine._extract_slug = MagicMock(return_value="slug")
            engine._download_image = MagicMock(
                return_value="~/assets/images/editorial-policy-test.png"
            )

            return engine

    def test_enforcement_fail_open_no_score(self, engine):
        """Test 1: cached_score None -> allowed (fail-open)"""
        engine.auditor.get_cached_score.return_value = None

        allowed = engine._enforce_editorial_policy("test_id", None)
        assert allowed is True

    def test_enforcement_blocked_low_score(self, engine):
        """Test 2: cached_score below threshold -> blocked"""
        # Standard mode threshold is 8.0
        score = {"epistemic_rigor_score": 7.9, "has_proper_caveats": True}

        allowed = engine._enforce_editorial_policy("test_id", score)
        assert allowed is False

    def test_enforcement_allowed_high_score(self, engine):
        """Test 3: cached_score above threshold -> allowed"""
        score = {"epistemic_rigor_score": 8.0, "has_proper_caveats": True}

        allowed = engine._enforce_editorial_policy("test_id", score)
        assert allowed is True

    def test_enforcement_blocked_missing_caveats(self, engine):
        """Test 4: missing caveats when required -> blocked"""
        # Standard mode requires caveats
        engine.policy.require_caveats = True

        # Case A: Explicit False
        score_false = {"epistemic_rigor_score": 9.0, "has_proper_caveats": False}
        assert engine._enforce_editorial_policy("test_id", score_false) is False

        # Case B: Missing Key (Strict default check)
        score_missing = {"epistemic_rigor_score": 9.0}
        assert engine._enforce_editorial_policy("test_id", score_missing) is False

    def test_persistence_prevention(self, engine, tmp_path):
        """Test 5: manifest and file not created when blocked"""
        # Setup Blocked State
        score = {"epistemic_rigor_score": 5.0}  # Low score
        engine.auditor.get_cached_score.return_value = score

        # Mock process inputs
        article = {
            "id": "test_persistence",
            "title": "Test with valid length",
            "url": "http://x",
            "summary": "This is a sufficiently long summary for editorial policy validation.",
            "image_url": "https://example.com/editorial-policy.png",
            "source_id": "src",
            "source_name": "src",
            "category": "cat",
            "published_date": __import__("datetime").datetime(2024, 1, 1),
            "source_metadata": {},
        }
        target_dir = tmp_path

        # Mock successful editor processing
        engine.editor.process_article.return_value = "Refined content"

        # Execute
        result = engine.process_single_article(article, MagicMock(), target_dir)

        # Verify Result
        assert result is False

        # Verify Persistence WAS NOT called
        # 1. File Write
        # We need to check if write_text was called on the path object returned by posts_dir / ...
        # Since target_dir is a mock, target_dir / ... returns another mock.
        # But checking specific calls on deep mocks is tricky.
        # Let's verify write_article was NOT called.
        engine.writer.write_article.assert_not_called()

        # 2. Git Branch/PR
        engine.git.create_branch.assert_not_called()
        engine.git.create_pull_request.assert_not_called()

    def test_persistence_allowed(self, engine, tmp_path):
        """Test 6: Persistence occurs when allowed"""
        # Setup Allowed State
        score = {"epistemic_rigor_score": 8.5, "has_proper_caveats": True}
        engine.auditor.get_cached_score.return_value = score

        article = {
            "id": "test_allowed",
            "title": "Test with valid length",
            "url": "http://x",
            "summary": "This is a sufficiently long summary for editorial policy validation.",
            "image_url": "https://example.com/editorial-policy.png",
            "source_id": "src",
            "source_name": "src",
            "category": "cat",
            "published_date": __import__("datetime").datetime(2024, 1, 1),
            "source_metadata": {},
        }
        target_dir = tmp_path
        engine.editor.process_article.return_value = "Refined content"

        result = engine.process_single_article(article, MagicMock(), target_dir)

        assert result is True
        engine.writer.write_article.assert_called_once()
        engine.git.create_pull_request.assert_called_once()
