import pytest
from unittest.mock import MagicMock, patch
from news_collector.storage.database import DatabaseManager
from datetime import datetime

@pytest.fixture
def mock_db_manager():
    # DatabaseManager likely takes no args or config. 
    # Use empty init and mock the internal engine creation if needed
    # But for these tests we mock get_session anyway.
    
    # Try default init
    manager = DatabaseManager()
    manager.Session = MagicMock()
    return manager

def test_save_articles_bulk_chunking(mock_db_manager):
    """
    Verify that commits happen in chunks.
    N=105, batch_size=50 -> Expect 3 commits (50, 50, 5)
    """
    # Setup Mock Session
    session_mock = MagicMock()
    mock_db_manager.get_session = MagicMock(return_value=session_mock)
    session_mock.__enter__.return_value = session_mock
    
    # Force query to return a pre-configured mock regardless of arguments
    query_mock = MagicMock()
    # Chain: query().filter_by().with_entities().first() -> None
    query_mock.filter_by.return_value.with_entities.return_value.first.return_value = None
    session_mock.query.return_value = query_mock
    # Also handle if side_effect is preferred to ignore args
    session_mock.query.side_effect = lambda *args, **kwargs: query_mock
    
    mock_db_manager._assign_cluster = MagicMock(return_value=(1, 0.9)) # cluster_id, confidence
    mock_db_manager._ensure_timezone = MagicMock(return_value=datetime.now())
    
    # Create 105 distinct articles
    articles_data = [{
        "url": f"http://example.com/u{i}", 
        "title": "Valid Title Length", 
        "summary": "This is a valid summary that is long enough." + ("." * 500),
        "content": "Content matches rules." + ("." * 500),
        "source_id": "src", 
        "source_name": "Source Name",
        "category": "cat",
        "published_date": datetime.now(),
        "word_count": 100,
        "reading_time_minutes": 5,
        "language": "en"
    } for i in range(105)]
    
    # Execute with explicit batch_size
    mock_db_manager.save_articles_bulk(articles_data, batch_size=50)
    
    # Assertions
    # Check that we actually added 105 items
    assert session_mock.add.call_count == 105
    # Check 3 commits
    assert session_mock.commit.call_count == 3

def test_save_articles_bulk_exact_chunk(mock_db_manager):
    """
    Verify N=100, batch_size=50 -> Expect 3 commits (50, 50, 0-leftover)
    """
    session_mock = MagicMock()
    mock_db_manager.get_session = MagicMock(return_value=session_mock)
    session_mock.__enter__.return_value = session_mock
    
    query_mock = MagicMock()
    query_mock.filter_by.return_value.with_entities.return_value.first.return_value = None
    session_mock.query.side_effect = lambda *args, **kwargs: query_mock
    
    mock_db_manager._assign_cluster = MagicMock(return_value=(1, 0.9))
    mock_db_manager._ensure_timezone = MagicMock(return_value=datetime.now())

    articles_data = [{
        "url": f"http://example.com/u{i}", 
        "title": "Valid Title Length", 
        "summary": "This is a valid summary that is long enough." + ("." * 500),
        "content": "Content matches rules." + ("." * 500),
        "source_id": "src", 
        "source_name": "Source Name",
        "category": "cat",
        "published_date": datetime.now(),
        "word_count": 100,
        "reading_time_minutes": 5,
        "language": "en"
    } for i in range(100)]
    
    mock_db_manager.save_articles_bulk(articles_data, batch_size=50)
    
    assert session_mock.add.call_count == 100
    assert session_mock.commit.call_count == 3

def test_save_articles_bulk_empty(mock_db_manager):
    """Verify 0 items -> 0 commits."""
    session_mock = MagicMock()
    mock_db_manager.get_session = MagicMock(return_value=session_mock)
    
    mock_db_manager.save_articles_bulk([], batch_size=50)
    
    assert session_mock.commit.call_count == 0
    # Also verify getting session wasn't even called if optimized
    mock_db_manager.get_session.assert_not_called()

def test_save_articles_no_batch_argument(mock_db_manager):
    """Verify backwards compatibility (default param)."""
    session_mock = MagicMock()
    mock_db_manager.get_session = MagicMock(return_value=session_mock)
    session_mock.__enter__.return_value = session_mock
    
    query_mock = MagicMock()
    query_mock.filter_by.return_value.with_entities.return_value.first.return_value = None
    session_mock.query.side_effect = lambda *args, **kwargs: query_mock
    
    mock_db_manager._assign_cluster = MagicMock(return_value=(1, 0.9))
    mock_db_manager._ensure_timezone = MagicMock(return_value=datetime.now())
    
    articles_data = [{
        "url": "http://example.com/u1", 
        "title": "Valid Title Length", 
        "summary": "This is a valid summary that is long enough." + ("." * 500),
        "content": "Content matches rules." + ("." * 500),
        "source_id": "src", 
        "source_name": "Source Name",
        "category": "cat",
        "published_date": datetime.now(),
        "word_count": 100,
        "reading_time_minutes": 5,
        "language": "en"
    }]
    
    # Call without batch_size
    mock_db_manager.save_articles_bulk(articles_data)
    
    assert session_mock.add.call_count == 1
    # Should commit once at end
    assert session_mock.commit.call_count == 1
