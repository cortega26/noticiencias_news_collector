import unittest

from news_collector.utils.url_canonicalizer import (
    canonicalize_url,
    clear_canonicalization_cache,
    configure_canonicalization_cache,
)


class TestUrlCanonicalizer(unittest.TestCase):

    def test_basic_normalization(self):
        # Scheme and case
        self.assertEqual(
            canonicalize_url("HTTP://Example.com/Path"), "https://example.com/Path"
        )
        # Default port removal
        self.assertEqual(
            canonicalize_url("https://example.com:443/"), "https://example.com/"
        )
        # http://example.com:80/ -> https://example.com:80/ (Port 80 preserved as it's not default for https)
        self.assertEqual(
            canonicalize_url("http://example.com:80/"), "https://example.com:80/"
        )
        # Trailing slash path normalization
        self.assertEqual(
            canonicalize_url("https://example.com/path/"), "https://example.com/path/"
        )

    def test_tracking_params(self):
        # Remove utm_*, fbclid, etc.
        url = "https://example.com?utm_source=twitter&fbclid=123&q=search"
        self.assertEqual(canonicalize_url(url), "https://example.com/?q=search")

        # Sort params
        url = "https://example.com?b=2&a=1"
        self.assertEqual(canonicalize_url(url), "https://example.com/?a=1&b=2")

    def test_mobile_amp_host(self):
        self.assertEqual(
            canonicalize_url("https://m.example.com/story"), "https://example.com/story"
        )
        self.assertEqual(
            canonicalize_url("https://www.example.com/story"),
            "https://example.com/story",
        )
        self.assertEqual(
            canonicalize_url("https://amp.example.com/story"),
            "https://example.com/story",
        )

    def test_amp_path(self):
        self.assertEqual(
            canonicalize_url("https://example.com/story/amp"),
            "https://example.com/story/",
        )
        self.assertEqual(
            canonicalize_url("https://example.com/story.amp"),
            "https://example.com/story/",
        )

    def test_schemeless(self):
        self.assertEqual(canonicalize_url("example.com/foo"), "https://example.com/foo")
        self.assertEqual(
            canonicalize_url("//example.com/foo"), "https://example.com/foo"
        )

    def test_empty(self):
        self.assertEqual(canonicalize_url(""), "")
        self.assertEqual(canonicalize_url(None), None)

    def test_caching(self):
        # Basic smoke test for cache functions
        configure_canonicalization_cache(100)
        clear_canonicalization_cache()
        # Verify it still works
        self.assertEqual(canonicalize_url("example.com"), "https://example.com/")


if __name__ == "__main__":
    unittest.main()
