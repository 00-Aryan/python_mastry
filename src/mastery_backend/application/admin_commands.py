"""Shared admin authorization and durable command replay in one transaction."""

from collections.abc import Callable
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from mastery_backend.application.command_replay import (
    CommandResult as CommandResult,
)
from mastery_backend.application.command_replay import (
    record_command,
    replay_command,
    request_hash,
)
from mastery_backend.domain.content import ContentError
from mastery_backend.domain.identity import Principal, require_content_admin
from mastery_backend.infrastructure.database.identity_repository import load_principal


class AdminCommands:
    def __init__(self, factory: sessionmaker[Session]) -> None:
        self.factory = factory

    def authorize(self, session: Session, principal: Principal) -> None:
        require_content_admin(principal)
        require_content_admin(load_principal(session, principal.user_id, lock=True))

    def replay(
        self, session: Session, principal: Principal, operation: str, key: str, request_hash: str
    ) -> CommandResult | None:
        return replay_command(session, principal, operation, key, request_hash)

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
                record_command(session, principal, operation, key, request_hash, result)
                return result
        except IntegrityError:
            raise ContentError(
                "CONTENT_CONFLICT", "Content conflicts with an existing record or constraint."
            ) from None

    @staticmethod
    def request_hash(payload: dict[str, Any]) -> str:
        return request_hash(payload)
