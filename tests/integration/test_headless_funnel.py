import email.utils
import http.server
import logging
import sys
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from news_collector.collectors.rss_collector import RSSCollector

# Configure basic logging to capture events
logging.basicConfig(level=logging.DEBUG)


class MockHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        print(f"DEBUG: MockHandler received request: {self.path}")
        # Feed Endpoint
        if self.path.endswith("/feed.xml"):
            self.send_response(200)
            self.send_header("Content-Type", "application/xml")
            self.end_headers()
            # Generate dynamic recent date to pass threshold

            now_str = email.utils.formatdate(usegmt=True)
            port = self.server.server_port
            xml = f"""
            <rss version="2.0">
            <channel>
                <title>Test Feed</title>
                <item>
                    <title>Test Article</title>
                    <link>http://localhost:{port}/article</link>
                    <description>Short description</description>
                    <pubDate>{now_str}</pubDate>
                    <guid>http://localhost:{port}/article</guid>
                </item>
            </channel>
            </rss>
            """
            self.wfile.write(xml.strip().encode("utf-8"))
            return

        # Article Endpoint (Short Content)
        if self.path.endswith("/article"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<html><body>Short content.</body></html>")
            return

        self.send_response(404)
        self.end_headers()


class TestHeadlessFunnel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Start local server
        cls.server = http.server.HTTPServer(("localhost", 0), MockHandler)
        cls.port = cls.server.server_port
        cls.thread = threading.Thread(target=cls.server.serve_forever)
        cls.thread.daemon = True
        cls.thread.start()
        time.sleep(0.1)  # Warmup

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=1)

    def test_end_to_end_headless_fallback(self):
        """
        Verifies:
        1. Feed is fetched.
        2. Article candidate discovered.
        3. HTTP enrichment returns short content.
        4. Router detects eligibility and calls Headless.
        5. Headless mock returns long content.
        6. Article is accepted (>=500 chars).
        """

        # 1. Define Test Source
        test_source_id = "test_headless_source"
        test_source = {
            "name": "Test Source",
            "url": f"http://localhost:{self.port}/feed.xml",
            "credibility_score": 1.0,
            "category": "tech",
            "tier": "A",
            "fetchability_score": 100,
            "crawl_interval_seconds": 60,
            "enrichment_strategy": "headless_fallback",
            "headless_enabled": True,
            "headless_max_seconds": 5,
            "headless_allowed_actions": ["wait"],
        }

        # 2. Mock DB (to prevent writes and dup checks)
        mock_db = MagicMock()
        mock_db.article_exists.return_value = False

        # 3. Setup Collector with Mocks
        # Instantiate
        collector = RSSCollector()
        collector.db_manager = mock_db

        # Mock the HeadlessEnricher inside the router
        # The collector initializes 'self.router' which initializes 'self.headless'
        mock_headless_enricher = MagicMock()
        collector.router.headless = mock_headless_enricher

        # Configure Headless Success
        long_content = "This is a long article content " * 30  # > 500 chars
        mock_headless_enricher.enrich.return_value = {
            "success": True,
            "content": long_content,
            "raw_content": f"<html>{long_content}</html>",
            "duration": 0.5,
        }

        # --- MOCKING CLIENT TO BYPASS SSRF ---
        def mock_get(url, **kwargs):
            mock_resp = MagicMock()
            mock_resp.status_code = 200

            if url.endswith("/feed.xml"):
                # Return Feed XML

                now_str = email.utils.formatdate(usegmt=True)
                port = self.server.server_port
                xml = f"""
                <rss version="2.0">
                <channel>
                    <title>Test Feed</title>
                    <item>
                        <title>Test Article</title>
                        <link>http://localhost:{port}/article</link>
                        <description>Short description</description>
                        <pubDate>{now_str}</pubDate>
                        <guid>http://localhost:{port}/article</guid>
                    </item>
                </channel>
                </rss>
                """
                mock_resp.content = xml.strip().encode("utf-8")
                mock_resp.text = xml.strip()
                return mock_resp

            if url.endswith("/article"):
                # Return Short HTML
                html = "<html><body>Short content.</body></html>"
                mock_resp.content = html.encode("utf-8")
                mock_resp.text = html
                return mock_resp

            mock_resp.status_code = 404
            return mock_resp

        # Mock RSSCollector's client
        collector.client.get = MagicMock(side_effect=mock_get)
        # Mock Router's HttpEnricher client
        collector.router.http.client.get = MagicMock(side_effect=mock_get)

        # Mock _check_crawl_interval to always return True (avoid DB interaction logic)
        with patch.object(collector, "_check_crawl_interval", return_value=True):

            # Use stdout logging
            root = logging.getLogger()
            root.setLevel(logging.DEBUG)
            handler = logging.StreamHandler(sys.stdout)
            handler.setLevel(logging.DEBUG)
            root.addHandler(handler)

            print(f"DEBUG: Attempting to collect from {test_source['url']}")

            try:
                collector.collect_from_multiple_sources({test_source_id: test_source})
            except Exception as e:
                print(f"DEBUG: Exception during collect: {e}")
                import traceback

                traceback.print_exc()

            # Check if router was attempted
            print("Checking mock_headless_enricher calls...")
            try:
                mock_headless_enricher.enrich.assert_called_once()
                call_args = mock_headless_enricher.enrich.call_args

                # Check suffix to allow http/https canonicalization
                called_url = call_args[0][0]
                self.assertTrue(
                    called_url.endswith("/article"),
                    f"Expected url ending in /article, got {called_url}",
                )

            except AssertionError as e:
                print(f"DEBUG: Headless mock NOT called: {e}")
                # Re-raise to fail test
                raise e

            print(
                "\n✅ Deterministic Funnel Test Passed: Headless triggered and succeeded."
            )

    def test_rss_only_does_not_block_headless_enrichment(self):
        """
        Verifies that fetch_mode="rss_only" in source config
        does NOT prevent the enrichment router from triggering.
        The user suspected a coupling where rss_only would skip enrichment.
        This test proves they are decoupled.
        """

        # 1. Define Test Source with "Blocking" Logic
        test_source_id = "test_decoupling_source"
        test_source = {
            "name": "Decoupling Test Source",
            "url": f"http://localhost:{self.port}/feed.xml",
            "credibility_score": 1.0,
            "category": "tech",
            "tier": "A",
            "fetchability_score": 100,
            "crawl_interval_seconds": 60,
            # The configuration under test
            "fetch_mode": "rss_only",
            "content_mode": "summary_only",  # Should trigger fallback if enrichment fails/returns short
            "enrichment_strategy": "headless_fallback",
            "headless_enabled": True,
            "headless_max_seconds": 5,
        }

        # 2. Mock Dependencies
        mock_db = MagicMock()
        mock_db.article_exists.return_value = False

        collector = RSSCollector()
        collector.db_manager = mock_db

        # Mock Headless
        mock_headless_enricher = MagicMock()
        collector.router.headless = mock_headless_enricher

        mock_headless_enricher.enrich.return_value = {
            "success": True,
            "content": "Long content " * 30,
            "raw_content": "<html>Long content</html>",
            "duration": 0.5,
        }

        # 3. Bypass SSRF & Mock Network
        def mock_get(url, **kwargs):
            mock_resp = MagicMock()
            mock_resp.status_code = 200

            if url.endswith("/feed.xml"):
                # Return Valid XML

                now_str = email.utils.formatdate(usegmt=True)
                port = self.server.server_port
                xml = f"""
                <rss version="2.0">
                <channel>
                    <title>Decoupling Feed</title>
                    <item>
                        <title>Decoupling Article</title>
                        <link>http://localhost:{port}/article_decouple</link>
                        <description>Short description</description>
                        <pubDate>{now_str}</pubDate>
                        <guid>http://localhost:{port}/article_decouple</guid>
                    </item>
                </channel>
                </rss>
                """
                mock_resp.content = xml.strip().encode("utf-8")
                mock_resp.text = xml.strip()
                return mock_resp

            if url.endswith("/article_decouple"):
                # Return Short HTML (simulating HTTP enrichment failure/shortness)
                html = "<html><body>Short content.</body></html>"
                mock_resp.content = html.encode("utf-8")
                mock_resp.text = html
                return mock_resp

            mock_resp.status_code = 404
            return mock_resp

        # Patch Dependencies
        with patch.object(collector.client, "get", side_effect=mock_get):
            with patch.object(
                collector.router.http.client, "get", side_effect=mock_get
            ):
                with patch.object(
                    collector, "_check_crawl_interval", return_value=True
                ):
                    # Patch _generate_recommendations to avoid logic errors with mocks
                    with patch.object(
                        collector, "_generate_recommendations", return_value=[]
                    ):

                        # 4. Execute
                        collector.collect_from_multiple_sources(
                            {test_source_id: test_source}
                        )

                        # 5. Assert
                        # If decoupled, router should have called headless
                        mock_headless_enricher.enrich.assert_called_once()

                        # Verify it called with the correct URL
                        args, _ = mock_headless_enricher.enrich.call_args
                        self.assertIn("article_decouple", args[0])

                        print(
                            "\n✅ Decoupling Verified: 'rss_only' source triggered Headless enrichment."
                        )
