"""Structured logs with safe exception frames and request-local context."""

import json
import logging
import sys
import traceback
from contextvars import ContextVar
from datetime import UTC, datetime

request_id_context: ContextVar[str | None] = ContextVar("request_id", default=None)
logger = logging.getLogger("mastery_backend")


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "event": record.getMessage(),
            "request_id": request_id_context.get(),
        }
        for field in (
            "operation",
            "status_code",
            "duration_ms",
            "attempt_id",
            "revision",
            "policy_version",
            "state_before",
            "state_after",
        ):
            if hasattr(record, field):
                payload[field] = getattr(record, field)
        if record.exc_info and record.exc_info[0]:
            # Preserve frames for diagnosis without logging exception values or code.
            payload["exception"] = {
                "type": record.exc_info[0].__name__,
                "frames": [
                    {"file": frame.filename, "line": frame.lineno, "function": frame.name}
                    for frame in traceback.extract_tb(record.exc_info[2])
                ],
            }
        return json.dumps(payload)


def configure_logging(level: str) -> None:
    """Repeated app factories must not install duplicate handlers."""
    if not any(getattr(handler, "mastery_handler", False) for handler in logger.handlers):
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonLogFormatter())
        handler.mastery_handler = True  # type: ignore[attr-defined]
        logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False
