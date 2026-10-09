"""Durable POST retry rules shared by admin and learner commands."""

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from mastery_backend.domain.content import ContentError
from mastery_backend.domain.identity import Principal
from mastery_backend.infrastructure.database.content_models import IdempotencyRecord


@dataclass(frozen=True)
class CommandResult:
    body: dict[str, Any]
    status_code: int = 200
    location: str | None = None
    replayed: bool = False


def request_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def replay_command(
    session: Session, principal: Principal, operation: str, key: str, payload_hash: str
) -> CommandResult | None:
    record = session.get(IdempotencyRecord, (principal.user_id, operation, key))
    if record is None:
        return None
    if record.expires_at <= datetime.now(UTC):
        session.delete(record)
        session.flush()
        return None
    if record.request_hash != payload_hash:
        raise ContentError("IDEMPOTENCY_CONFLICT", "Idempotency key was used with different input.")
    return CommandResult(record.response_json, record.status_code, record.location, True)


def record_command(
    session: Session,
    principal: Principal,
    operation: str,
    key: str,
    payload_hash: str,
    result: CommandResult,
) -> None:
    session.add(
        IdempotencyRecord(
            principal_id=principal.user_id,
            operation=operation,
            key=key,
            request_hash=payload_hash,
            response_json=result.body,
            status_code=result.status_code,
            location=result.location,
            expires_at=datetime.now(UTC) + timedelta(days=7),
        )
    )
    session.flush()
