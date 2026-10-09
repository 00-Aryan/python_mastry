"""Server-side identity lookup; role grants are stored facts, never headers."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from mastery_backend.domain.content import ContentError
from mastery_backend.domain.identity import Principal
from mastery_backend.infrastructure.database.content_models import User, UserRole


def load_principal(session: Session, user_id: UUID | None, *, lock: bool = False) -> Principal:
    if user_id is None:
        raise ContentError("UNAUTHENTICATED", "Configure a seeded local development identity.")
    query = select(User).where(User.id == user_id, User.status == "active")
    if lock:
        query = query.with_for_update()
    if session.scalar(query) is None:
        raise ContentError("UNAUTHENTICATED", "The configured identity is unavailable.")
    roles = frozenset(session.scalars(select(UserRole.role).where(UserRole.user_id == user_id)))
    return Principal(user_id, roles)
