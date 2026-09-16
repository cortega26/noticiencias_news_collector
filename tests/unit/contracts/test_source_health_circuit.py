"""Contract tests for health-record circuit fields (Plan 110).

The three `circuit_*` fields are optional read-time enrichment: export
files written before the merge (and sources with no DB row) validate
unchanged.
"""

from news_collector.contracts.source_health import SourceHealthRecord


def _base_record(**overrides):
    payload = {
        "source_id": "nature",
        "operational_state": "healthy_full_text",
    }
    payload.update(overrides)
    return SourceHealthRecord(**payload)


def test_record_valid_without_circuit_fields() -> None:
    record = _base_record()
    assert record.circuit_status is None
    assert record.circuit_next_retry_at is None
    assert record.circuit_consecutive_failures is None


def test_record_accepts_cooldown_state() -> None:
    record = _base_record(
        circuit_status="COOLDOWN",
        circuit_next_retry_at="2026-09-20T00:00:00+00:00",
        circuit_consecutive_failures=3,
    )
    assert record.circuit_status == "COOLDOWN"
    assert record.circuit_consecutive_failures == 3
