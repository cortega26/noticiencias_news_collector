
import unittest
from unittest.mock import MagicMock, patch
from news_collector.utils.full_text import fetch_full_article

class TestFullText(unittest.TestCase):

    def setUp(self):
        self.mock_response = MagicMock()
        self.mock_response.raise_for_status = MagicMock()

    @patch('news_collector.utils.full_text.requests.get')
    def test_fetch_full_article_success(self, mock_get):
        self.mock_response.content = b"<html><body><article><p>Article content</p></article></body></html>"
        mock_get.return_value = self.mock_response
        
        text = fetch_full_article("http://example.com")
        self.assertEqual(text, "Article content")
        mock_get.assert_called_once()

    @patch('news_collector.utils.full_text.requests.get')
    def test_cleanup_tags(self, mock_get):
        html = b"""
        <html>
            <body>
                <script>bad</script>
                <style>bad</style>
                <nav>bad</nav>
                <article>
                    <p>Good Content</p>
                </article>
                <footer>bad</footer>
            </body>
        </html>
        """
        self.mock_response.content = html
        mock_get.return_value = self.mock_response
        
        text = fetch_full_article("http://example.com")
        self.assertEqual(text, "Good Content")

    @patch('news_collector.utils.full_text.requests.get')
    def test_fallback_structure(self, mock_get):
        # Fallback to main
        self.mock_response.content = b"<html><body><main>Main Content</main></body></html>"
        mock_get.return_value = self.mock_response
        self.assertEqual(fetch_full_article("http://example.com"), "Main Content")
        
        # Fallback to body
        self.mock_response.content = b"<html><body>Body Content</body></html>"
        mock_get.return_value = self.mock_response
        self.assertEqual(fetch_full_article("http://example.com"), "Body Content")

    @patch('news_collector.utils.full_text.requests.get')
    def test_fetch_error(self, mock_get):
        mock_get.side_effect = Exception("Network fail")
        text = fetch_full_article("http://example.com")
        self.assertEqual(text, "")

    def test_with_session(self):
        session = MagicMock()
        session.get.return_value = self.mock_response
        self.mock_response.content = b"<html><body>Content</body></html>"
        
        text = fetch_full_article("http://example.com", session=session)
        session.get.assert_called_once()
        self.assertEqual(text, "Content")

if __name__ == '__main__':
    unittest.main()
