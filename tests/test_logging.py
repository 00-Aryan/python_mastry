import json
import logging
import sys

from mastery_backend.infrastructure.observability.logging import (
    JsonLogFormatter,
    request_id_context,
)


def test_logs_retain_frames_without_secret_exception_values() -> None:
    try:
        raise RuntimeError("secret-database-password")
    except RuntimeError:
        record = logging.LogRecord(
            "mastery_backend", logging.ERROR, __file__, 1, "request_failed", (), sys.exc_info()
        )
    token = request_id_context.set("request_123")
    try:
        encoded = JsonLogFormatter().format(record)
    finally:
        request_id_context.reset(token)
    result = json.loads(encoded)
    assert result["request_id"] == "request_123"
    assert result["exception"]["type"] == "RuntimeError"
    assert result["exception"]["frames"]
    assert "secret-database-password" not in encoded
