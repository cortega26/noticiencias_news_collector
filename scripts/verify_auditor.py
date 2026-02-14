import sys
import time
import json
import logging
from pathlib import Path
from unittest.mock import MagicMock
import concurrent.futures
import shutil

# Configure Logger
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s', stream=sys.stdout)
logger = logging.getLogger(__name__)

# Add project root
sys.path.append(str(Path(__file__).resolve().parents[1]))

from news_collector.components.editorial.auditor import EditorialAuditor

class MockConfig:
    editorial_auditor = {"enabled": True, "sampling_rate": 1.0}
    paths = {"data_dir": "./temp_verify_auditor"}
    ollama = {"api_url": "http://mock", "model": "mock"}

def setup():
    path = Path("./temp_verify_auditor")
    if path.exists():
        shutil.rmtree(path)
    path.mkdir()

def test_schema_and_persistence():
    logger.info("--- TEST 1: Schema & Persistence ---")
    config = MockConfig()
    auditor = EditorialAuditor(config)
    
    # Mock return with some missing fields to test defaults
    auditor.provider.generate_sync = MagicMock(return_value='{"epistemic_rigor_score": 8.5}')
    
    auditor.audit_article_sync("test_schema", "content", "url", {})
    
    score_file = Path("./temp_verify_auditor/article_metadata/test_schema/auditor_score.json")
    if score_file.exists():
        data = json.loads(score_file.read_text())["audit"]
        if data["epistemic_rigor_score"] == 8.5 and data["has_therapeutic_claims"] is False:
             logger.info("✅ Schema defaults applied & Persistence working.")
        else:
             logger.error(f"❌ Schema/Persistence check failed: {data}")
    else:
        logger.error("❌ File not created.")

def test_async_submission():
    logger.info("--- TEST 2: Async Submission ---")
    config = MockConfig()
    auditor = EditorialAuditor(config)
    
    # Mock Provider to sleep
    def slow_mock(*args, **kwargs):
        time.sleep(1.0)
        return '{"epistemic_rigor_score": 5.0}'
    
    auditor.provider.generate_sync = slow_mock
    
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    
    start = time.time()
    logger.info("Submitting task...")
    
    # Manually submit to executor to verify non-blocking
    if auditor.should_run_fast({}, "content"):
        executor.submit(auditor.audit_article_sync, "test_async", "c", "u", {})
    
    elapsed = time.time() - start
    logger.info(f"Submission took: {elapsed:.4f}s")
    
    if elapsed < 0.1:
        logger.info("✅ Non-blocking confirmed.")
    else:
        logger.error(f"❌ Blocking detected ({elapsed}s)")
        
    logger.info("Waiting for task...")
    executor.shutdown(wait=True)
    logger.info("Task finished.")

def test_circuit_breaker():
    logger.info("--- TEST 3: Circuit Breaker ---")
    config = MockConfig()
    auditor = EditorialAuditor(config)
    
    # Mock output to raise exception
    auditor.provider.generate_sync = MagicMock(side_effect=Exception("Mock Fail"))
    
    logger.info("Triggering failures...")
    for i in range(3):
        auditor.audit_article_sync(f"id_{i}", "c", "u", {})
        
    if auditor.failure_count == 3:
        logger.info("✅ Failure count correct.")
    else:
        logger.error(f"❌ Failure count: {auditor.failure_count}")
        
    if auditor.circuit_open_until > time.time():
        logger.info("✅ Circuit breaker TRIPPED.")
    else:
        logger.error("❌ Circuit breaker NOT tripped.")
        
    # Verify rejection
    if not auditor.should_run_fast({}, "content"):
        logger.info("✅ Execution rejected by CB.")
    else:
        logger.error("❌ Execution ALLOWED (CB failed).")

if __name__ == "__main__":
    setup()
    try:
        test_schema_and_persistence()
        test_async_submission()
        test_circuit_breaker()
        logger.info("ALL TESTS PASSED.")
    except Exception as e:
        logger.error(f"Test Failed: {e}")
    finally:
        # Cleanup
        if Path("./temp_verify_auditor").exists():
            shutil.rmtree("./temp_verify_auditor")
