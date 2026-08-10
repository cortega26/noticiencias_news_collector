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
        # http://example.com:80/ -> https://example.com/ (80 is the default
        # http port; after consolidating to https the explicit port is redundant)
        self.assertEqual(
            canonicalize_url("http://example.com:80/"), "https://example.com/"
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

    def test_schemeless_hostport(self):
        # Scheme-less host:port URLs are misread by urlparse as a scheme;
        # they must be rebuilt as https.
        self.assertEqual(
            canonicalize_url("example.com:80/foo"), "https://example.com/foo"
        )
        self.assertEqual(canonicalize_url("example.com:80"), "https://example.com/")
        self.assertEqual(
            canonicalize_url("example.com:8080/x"), "https://example.com:8080/x"
        )
        self.assertEqual(
            canonicalize_url("localhost:8080/x"), "https://localhost:8080/x"
        )

    def test_non_web_schemes_preserved(self):
        # Genuine non-web schemes (including ones with numeric paths that
        # could be mistaken for a host:port) must be preserved untouched.
        self.assertEqual(canonicalize_url("tel:12345"), "tel:12345")
        self.assertEqual(canonicalize_url("data:12345"), "data:12345")
        self.assertEqual(canonicalize_url("javascript:12345"), "javascript:12345")
        self.assertEqual(canonicalize_url("mailto:12345@x.com"), "mailto:12345@x.com")
        self.assertEqual(
            canonicalize_url("ftp://example.com/file"), "ftp://example.com/file"
        )
        self.assertEqual(
            canonicalize_url("https://example.com/file"), "https://example.com/file"
        )

    def test_real_mobile_hosts_not_mangled(self):
        # m.com / mobile.com are real domains; the mobile-host prefix strip
        # must not turn them into their suffix.
        self.assertEqual(canonicalize_url("https://m.com/story"), "https://m.com/story")
        self.assertEqual(
            canonicalize_url("https://mobile.com/x"), "https://mobile.com/x"
        )
        self.assertEqual(
            canonicalize_url("https://m.example.com/story"),
            "https://example.com/story",
        )

    def test_ipv6_hosts_with_default_ports(self):
        self.assertEqual(
            canonicalize_url("https://[2001:db8::1]:443/x"),
            "https://[2001:db8::1]/x",
        )
        self.assertEqual(canonicalize_url("https://[::1]:80/x"), "https://[::1]/x")
        self.assertEqual(canonicalize_url("https://[::1]/x"), "https://[::1]/x")

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
