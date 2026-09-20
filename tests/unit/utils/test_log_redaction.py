from loguru import logger

from news_collector.utils.logger import redact_record, redact_secrets

_URL = (
    "404 Client Error: Not Found for url: https://generativelanguage.googleapis.com/"
    "v1beta/models/x:generateContent?key=AQ.SECRETSECRET123&alt=sse"
)


def test_query_key_is_redacted_but_the_rest_is_kept():
    out = redact_secrets(_URL)
    assert "SECRET" not in out
    assert "?key=[REDACTED]&alt=sse" in out


def test_other_secret_shapes_and_clean_text():
    assert (
        redact_secrets("GET /x?api_key=abc123&y=1") == "GET /x?api_key=[REDACTED]&y=1"
    )
    token = "Bearer " + "a" * 30
    assert (
        redact_secrets(f"Authorization: {token}") == "Authorization: Bearer [REDACTED]"
    )
    assert redact_secrets("nada que ocultar, key=valor sin ?") == (
        "nada que ocultar, key=valor sin ?"
    )


def test_patcher_redacts_every_sink():
    seen = []
    handler_id = logger.add(lambda m: seen.append(m.record["message"]), level="DEBUG")
    logger.configure(patcher=redact_record)
    try:
        logger.warning("Provider gemini failed: {}", _URL)
    finally:
        logger.configure(patcher=lambda r: None)
        logger.remove(handler_id)
    assert seen and "SECRET" not in seen[0] and "[REDACTED]" in seen[0]
