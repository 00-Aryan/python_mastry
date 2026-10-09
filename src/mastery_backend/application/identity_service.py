"""Local identity use cases and short transactions."""

from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from mastery_backend.domain.identity import Principal
from mastery_backend.infrastructure.database.identity_repository import load_principal


def read_development_principal(factory: sessionmaker[Session], user_id: UUID | None) -> Principal:
    with factory.begin() as session:
        return load_principal(session, user_id)
