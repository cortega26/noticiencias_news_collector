"""Unit tests for the serving X-Request-ID middleware.

The middleware accepts-or-mints ``X-Request-ID``: a caller-supplied header is
echoed back, otherwise a UUID hex is generated. It also binds the ID to the
loguru context for the request lifetime so log records can be correlated with
the response that carried them.
"""

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from loguru import logger as loguru_logger

from news_collector.serving.api import _RequestIDMiddleware
from news_collector.serving.api import logger as serving_logger


def _build_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(_RequestIDMiddleware)

    @app.get("/ping")
    async def ping(request: Request):
        serving_logger.info("ping handled")
        return {"request_id": request.state.request_id}

    return app


def test_mints_request_id_when_header_absent():
    response = TestClient(_build_app()).get("/ping")
    assert response.status_code == 200
    request_id = response.headers.get("X-Request-ID")
    assert request_id
    assert response.json()["request_id"] == request_id


def test_echoes_caller_supplied_request_id():
    response = TestClient(_build_app()).get(
        "/ping", headers={"X-Request-ID": "trace-abc-123"}
    )
    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "trace-abc-123"
    assert response.json()["request_id"] == "trace-abc-123"


def test_binds_request_id_to_loguru_context():
    records = []
    sink_id = loguru_logger.add(
        lambda message: records.append(message.record), level="INFO"
    )
    try:
        response = TestClient(_build_app()).get(
            "/ping", headers={"X-Request-ID": "trace-abc-123"}
        )
    finally:
        loguru_logger.remove(sink_id)

    assert response.status_code == 200
    matching = [record for record in records if record["message"] == "ping handled"]
    assert matching, "route log record was not captured"
    assert matching[-1]["extra"]["request_id"] == "trace-abc-123"
