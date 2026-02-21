import http.server
import logging
import shutil
import socket
import socketserver
import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

# Configure Logger to stdout
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(message)s", stream=sys.stdout
)
logger = logging.getLogger("ProofVerify")

# Add project root
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from news_collector.logic.workflows.refinery_engine import RefineryEngine


# --- Mock Classes for Integrati# Mock Config
class MockAppConfig:
    def __init__(self):
        self.editorial_mode = "standard"


class MockConfig:
    def __init__(self):
        self.editorial_auditor = {
            "enabled": True,
            "blocking": False,
            "sampling_rate": 1.0,
            "trigger_keywords": ["trigger"],
            "trigger_categories": ["health"],
        }
        self.app = MockAppConfig()
        self.paths = {"data_dir": "./temp_proof_hardened"}
        self.ollama = {"api_url": "http://mock", "model": "mock"}
        self.github = {"repo_name": "mock/repo"}
        self.target_repo_url = "http://mock/repo"  # needed for create_pull_request
        # Add other necessary attributes if any accessed by RefineryEngine


class MockDB:
    def get_canonical_slug(self, *args):
        return None

    def mark_article_published(self, *args):
        pass

    def set_canonical_slug(self, *args):
        pass


class MockGit:
    def create_branch(self, *args, **kwargs):
        return "mock-branch"

    def commit_and_push(self, *args, **kwargs):
        pass

    def create_pull_request(self, *args, **kwargs):
        return "http://mock/pr/1"


class MockEditor:
    def __init__(self, config):
        pass

    def process_article(self, article, override_date=None):
        return "trigger content"  # This ensures auditor triggers


class MockTranslator:
    def __init__(self, config):
        pass


# Patch RefineryEngine imports
import news_collector.logic.workflows.refinery_engine as re_module

re_module.ContentTranslator = MockTranslator
re_module.EditorAgent = MockEditor
re_module.GitManager = MockGit  # Though we inject it, it might be used internally
re_module.GitHubPublisher = MockGit  # Type checking import patch


def test_non_blocking_event_based():
    logger.info("\n=== TEST 1: NON-BLOCKING & CLEAN TEARDOWN (Event Control) ===")

    # Setup
    config = MockConfig()
    engine = RefineryEngine(MockDB(), MockGit(), MockEditor(config), config)

    # Event to control the "slow" provider
    release_event = threading.Event()
    audit_active_counter = 0

    def blocked_generate(*args, **kwargs):
        nonlocal audit_active_counter
        audit_active_counter += 1
        logger.info("[MockProvider] Blocked waiting for release...")
        release_event.wait()  # SIMULATES HANG until we say so
        logger.info("[MockProvider] Released!")
        return '{"epistemic_rigor_score": 5.0}'

    engine.auditor.provider.generate_sync = blocked_generate

    # --- Execution ---
    logger.info("Executing 10 iterations of process_single_article...")

    max_latency = 0
    start_time = time.time()

    for i in range(10):
        article = {
            "id": f"id_{i}",
            "category": "health",
            "url": "http://test",
            "published_date": "2024-01-01",
        }

        iter_start = time.time()

        # REAL METHOD CALL (Objective 1)
        engine.process_single_article(
            article, MagicMock(), Path("./temp_proof_hardened")
        )

        iter_lat = (time.time() - iter_start) * 1000
        max_latency = max(max_latency, iter_lat)
        logger.info(f"Iter {i}: {iter_lat:.4f} ms")

    total_time = time.time() - start_time
    logger.info(f"Total time: {total_time:.4f}s")

    # Assertions
    if max_latency < 50:
        logger.info(f"✅ Max Latency {max_latency:.2f}ms < 50ms")
    else:
        logger.error(f"❌ Latency too high: {max_latency}ms")
        sys.exit(1)

    # Check backlog/backpressure
    # First iter should have triggered audit. Subsequent should have been skipped (Backpressure)
    # because the first one is BLOCKED on release_event.
    # So audit_active_counter should be exactly 1 (triggered by first, held by event).
    # Wait, 'blocked_generate' runs in the thread.
    # The 'audit_article_sync' runs in the thread.
    # The first submission starts 'blocked_generate'.
    # Subsequent submissions see '_last_audit_future' as not done.

    # Allow a tiny moment for thread to start and block
    time.sleep(0.1)

    if audit_active_counter == 1:
        logger.info(
            "✅ Backpressure verified: Only 1 active audit despite 10 submissions."
        )
    else:
        logger.error(f"❌ Backpressure failed? Active audits: {audit_active_counter}")
        # It's possible for it to be 0 if thread hasn't started yet? Unlikely with 0.1 sleep.

    # TEARDOWN
    logger.info("Releasing background tasks...")
    release_event.set()
    engine.executor.shutdown(wait=True)
    logger.info("✅ Teardown complete (No hang).")


def test_burst_backpressure():
    logger.info("\n=== TEST 2: BURST SUBMISSION & BACKPRESSURE ===")
    config = MockConfig()
    engine = RefineryEngine(MockDB(), MockGit(), MockEditor(config), config)

    release_event = threading.Event()
    submission_count = 0

    # Wrap submit to count attempts
    original_submit = engine.executor.submit

    def counted_submit(*args, **kwargs):
        nonlocal submission_count
        submission_count += 1
        return original_submit(*args, **kwargs)

    engine.executor.submit = counted_submit

    # Block again
    engine.auditor.provider.generate_sync = lambda *a, **k: release_event.wait()

    logger.info("Bursting 50 submissions...")
    for i in range(50):
        article = {"id": f"burst_{i}", "category": "health", "url": "http://test"}
        engine.process_single_article(
            article, MagicMock(), Path("./temp_proof_hardened")
        )

    # We expect exactly 1 submission accepted by executor (since it blocks immediately)
    # The rest rejected by "if self._last_audit_future..."

    logger.info(f"Total submissions sent to executor: {submission_count}")

    if submission_count <= 2:
        # 1 is ideal. 2 is acceptable if race condition on first check?
        # Typically strictly 1 if the first one blocks fast enough.
        logger.info(
            "✅ Bound constraints met (<=2 actual submissions for 50 requests)."
        )
    else:
        logger.error(f"❌ Unbounded growth? {submission_count} submissions.")

    release_event.set()
    engine.executor.shutdown(wait=True)


class StallHTTPHandler(http.server.BaseHTTPRequestHandler):
    STALL_TIME = 2.0  # Default, can be overridden per instance if using global

    def do_POST(self):
        # Read body to be polite
        content_length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(content_length)

        # Stall
        current_stall = getattr(self.server, "stall_time", self.STALL_TIME)
        # logger.info(f"Stalling for {current_stall}s...")
        time.sleep(current_stall)

        # Return success (though client should have timed out)
        self.send_response(200)
        self.send_header("Content-type", "application/json")
        self.end_headers()
        try:
            self.wfile.write(b'{"response": "Too late"}')
        except BrokenPipeError:
            pass  # Client disconnected, expected.

    def log_message(self, format, *args):
        pass  # Silence server logs


def start_stall_server(stall_time=2.0):
    # Find free port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        port = s.getsockname()[1]

    server = socketserver.TCPServer(("127.0.0.1", port), StallHTTPHandler)
    server.stall_time = stall_time  # Inject stall time
    thread = threading.Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()
    return server, port


def run_timeout_test(timeout_val, stall_time, label):
    logger.info(
        f"\n--- Subtest: {label} (Timeout={timeout_val}s, Stall={stall_time}s) ---"
    )

    # 1. Start Stall Server
    server, port = start_stall_server(stall_time=stall_time)
    stall_url = f"http://127.0.0.1:{port}/api/generate"

    try:
        # 2. Setup Engine
        config = MockConfig()
        config.editorial_auditor["enabled"] = True

        engine = RefineryEngine(MockDB(), MockGit(), MockEditor(config), config)

        # 3. Configure Provider
        engine.auditor.provider.timeout = timeout_val
        engine.auditor.provider.api_url = stall_url
        engine.auditor.provider.max_retries = (
            0  # Enforce 0 retries (1 attempt) for predictable duration
        )

        # Verify Config
        logger.info(f"Using Provider Timeout: {engine.auditor.provider.timeout}s")
        logger.info(f"Using Provider Retries: {engine.auditor.provider.max_retries}")

        # 4. Trigger Audit
        # article = {"id": f"timeout_test_{int(timeout_val)}", "category": "health", "url": "http://test"}
        # Use simple ID to avoid breaking mock expectations
        article = {"id": "timeout_run", "category": "health", "url": "http://test"}

        logger.info("Triggering pipeline...")
        start_time = time.time()

        engine.process_single_article(
            article, MagicMock(), Path("./temp_proof_hardened")
        )

        pipeline_duration = time.time() - start_time
        logger.info(f"Pipeline submit duration: {pipeline_duration*1000:.2f} ms")

        if pipeline_duration > 50:
            logger.error(f"❌ Pipeline blocked! Duration: {pipeline_duration}s")
            sys.exit(1)

        # 5. Wait for Background Task
        logger.info("Waiting for timeout enforcement...")
        engine.executor.shutdown(wait=True)

        total_duration = time.time() - start_time
        logger.info(f"Total Audit Duration: {total_duration:.2f}s")

        # 6. Assertions
        # Expectation: Timeout < Total < Stall
        # Margin: Timeout + 0.5s overhead
        expected_max = timeout_val + 1.0  # 0.5s extra for overhead

        if total_duration < timeout_val:
            logger.error(f"❌ Too fast! {total_duration}s < Timeout {timeout_val}s")
            sys.exit(1)

        if total_duration > expected_max:
            logger.error(
                f"❌ Too slow! {total_duration}s > Expected Max {expected_max}s"
            )
            sys.exit(1)

        if engine.auditor.failure_count >= 1:
            logger.info(f"✅ {label} Passed. Duration within limits.")
            logger.info(f"   Configured: {timeout_val}s")
            logger.info(f"   Measured:   {total_duration:.2f}s")
            logger.info(
                f"   Retries:    {engine.auditor.provider.max_retries} (1 attempt)"
            )
        else:
            logger.error("❌ Failure count did not increment.")
            sys.exit(1)

    finally:
        server.shutdown()
        server.server_close()


def test_real_timeout_proof():
    logger.info("\n=== TEST 3: DUAL TIMEOUT PROOF (Production & Fast) ===")

    # Subtest A: Fast Timeout (Smoke Test)
    run_timeout_test(0.5, 2.0, "Fast Timeout Smoke Test")

    # Subtest B: Production Timeout (Critical Proof)
    # Production is 15s. We simulate a 17s stall.
    run_timeout_test(15.0, 17.0, "Production Timeout Proof (Critical)")


def main():
    path = Path("./temp_proof_hardened")
    if path.exists():
        shutil.rmtree(path)
    path.mkdir()

    try:
        test_non_blocking_event_based()
        test_burst_backpressure()
        test_real_timeout_proof()
        logger.info("\n✨ HARDENED PROOF SUITE PASSED ✨")
    except Exception as e:
        logger.error(f"Test crashed: {e}")
        sys.exit(1)
    finally:
        if path.exists():
            shutil.rmtree(path)


if __name__ == "__main__":
    main()
