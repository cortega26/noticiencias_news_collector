import os
import shutil
import sqlite3
import unittest

# from scripts.generate_autonomous_report import main as generate_report


class TestReportGeneration(unittest.TestCase):

    def setUp(self):
        # Setup Test Environment
        self.test_dir = "data/metrics/production"  # Script defaults to this, so we must use it or patch the script
        # The script imports DB_PATH constant. We should patch it or just use the path.
        # But we are in "production" mode for report generation usually.

        # Let's mock the DB_PATH in the script module
        self.patcher = unittest.mock.patch(
            "scripts.generate_autonomous_report.DB_PATH",
            "data/metrics/test_report/enrichment_metrics.db",
        )
        self.mock_db_path = self.patcher.start()

        # Also need metrics store to write to THIS path
        # Hack: Init metrics store with test environment to write to test path, but rename it for the report script?
        # Easier to just use sqlite3 to populate dummy data at the path script expects.

        os.makedirs(os.path.dirname(self.mock_db_path), exist_ok=True)
        self.populate_db()

    def tearDown(self):
        self.patcher.stop()
        if os.path.exists("data/metrics/test_report"):
            shutil.rmtree("data/metrics/test_report")
        if os.path.exists("PRODUCTION_AUTONOMOUS_OPERATION_REPORT.md"):
            os.remove("PRODUCTION_AUTONOMOUS_OPERATION_REPORT.md")

    def populate_db(self):
        conn = sqlite3.connect(self.mock_db_path)
        cur = conn.cursor()

        # Create Tables (Simplified schema match)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS enrichment_metrics (
            source_id TEXT PRIMARY KEY,
            total_discovered INTEGER,
            total_enrichment_attempted INTEGER,
            total_publishable INTEGER,
            proxy_requests_used INTEGER DEFAULT 0,
            headless_seconds_used REAL DEFAULT 0.0,
            headless_success INTEGER DEFAULT 0,
            headless_attempts INTEGER DEFAULT 0,
            proxy_success INTEGER DEFAULT 0,
            proxy_attempts INTEGER DEFAULT 0,
            avg_enrichment_time REAL DEFAULT 0.0
        )
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS enrichment_history (
            id INTEGER PRIMARY KEY,
            event_type TEXT,
            strategy TEXT,
            metadata JSON
        )
        """)

        # Insert Metrics
        cur.execute(
            "INSERT INTO enrichment_metrics (source_id, total_discovered, total_enrichment_attempted, total_publishable) VALUES ('source_a', 10, 10, 5)"
        )

        # Insert History Failures
        import json

        meta = json.dumps({"reason": "headless_timeout"})
        cur.execute(
            "INSERT INTO enrichment_history (event_type, strategy, metadata) VALUES ('failure', 'headless', ?)",
            (meta,),
        )

        conn.commit()
        conn.close()

    def test_report_generation(self):
        # Run script as subprocess with custom env
        import subprocess

        env = os.environ.copy()
        env["METRICS_DB_PATH"] = self.mock_db_path

        result = subprocess.run(
            ["python3", "scripts/generate_autonomous_report.py"],
            capture_output=True,
            text=True,
            env=env,
        )

        self.assertEqual(result.returncode, 0, f"Script failed: {result.stderr}")
        self.assertTrue(os.path.exists("PRODUCTION_AUTONOMOUS_OPERATION_REPORT.md"))

        with open("PRODUCTION_AUTONOMOUS_OPERATION_REPORT.md", "r") as f:
            content = f.read()

        self.assertIn("source_a", content)
        self.assertIn("headless_timeout", content)
        self.assertIn("Top Failure Reasons", content)


if __name__ == "__main__":
    unittest.main()
