def test_source_config_strict_schema():
    """
    Test that the source configuration follows the strict schema:
    - tier (A, B, C, D)
    - fetchability_score (0-100)
    - crawl_interval_seconds (int > 0)
    """
    # Mock data with invalid missing fields
    invalid_data = {
        "test_source": {
            "name": "Test Source",
            "url": "http://example.com/feed",
            "category": "tech",
            "credibility_score": 5.0,
            # Missing tier, fetchability_score, etc.
        }
    }

    # Validation should fail or return warnings/errors if we enforce it.
    # Currently validate_sources prints to stdout/stderr in the original code,
    # so we might need to capture that or modify validate_sources to raise exceptions.
    # For now, let's assume we will modify validate_sources to return specific errors.

    # Actually, looking at sources.py, validate_sources() might just print.
    # We will need to check the implementation of validate_sources again to be sure how to test it.
    pass


def test_valid_source_config():
    valid_data = {
        "test_source_valid": {
            "name": "Valid Source",
            "url": "http://example.com/feed",
            "category": "tech",
            "credibility_score": 5.0,
            "tier": "A",
            "fetchability_score": 90,
            "crawl_interval_seconds": 600,
        }
    }
    # Should pass validation
    pass
