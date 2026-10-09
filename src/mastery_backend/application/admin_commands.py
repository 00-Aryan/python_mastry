"""Shared admin authorization and durable command replay in one transaction."""

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from mastery_backend.domain.content import ContentError
from mastery_backend.domain.identity import Principal, require_content_admin
from mastery_backend.infrastructure.database.content_models import IdempotencyRecord
from mastery_backend.infrastructure.database.identity_repository import load_principal


@dataclass(frozen=True)
class CommandResult:
    body: dict[str, Any]
    status_code: int = 200
    location: str | None = None
    replayed: bool = False


class AdminCommands:
    def __init__(self, factory: sessionmaker[Session]) -> None:
        self.factory = factory

    def authorize(self, session: Session, principal: Principal) -> None:
        require_content_admin(principal)
        require_content_admin(load_principal(session, principal.user_id, lock=True))

    def replay(
        self, session: Session, principal: Principal, operation: str, key: str, request_hash: str
    ) -> CommandResult | None:
        record = session.get(IdempotencyRecord, (principal.user_id, operation, key))
        if record is None:
            return None
        if record.expires_at <= datetime.now(UTC):
            session.delete(record)
            session.flush()
            return None
        if record.request_hash != request_hash:
            raise ContentError(
                "IDEMPOTENCY_CONFLICT", "Idempotency key was used with different input."
            )
        return CommandResult(record.response_json, record.status_code, record.location, True)

    def run(
        self,
        principal: Principal,
        operation: str,
        key: str,
        payload: dict[str, Any],
        action: Callable[[Session], CommandResult],
    ) -> CommandResult:
        request_hash = self.request_hash(payload)
        try:
            with self.factory.begin() as session:
                # One local principal's commands serialize at this short-lived lock.
                self.authorize(session, principal)
                replay = self.replay(session, principal, operation, key, request_hash)
                if replay is not None:
                    return replay
                result = action(session)
                session.add(
                    IdempotencyRecord(
                        principal_id=principal.user_id,
                        operation=operation,
                        key=key,
                        request_hash=request_hash,
                        response_json=result.body,
                        status_code=result.status_code,
                        location=result.location,
                        expires_at=datetime.now(UTC) + timedelta(days=7),
                    )
                )
                session.flush()
                return result
        except IntegrityError:
            raise ContentError(
                "CONTENT_CONFLICT", "Content conflicts with an existing record or constraint."
            ) from None

    @staticmethod
    def request_hash(payload: dict[str, Any]) -> str:
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        ).hexdigest()
