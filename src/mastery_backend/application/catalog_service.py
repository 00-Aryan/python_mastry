"""Read-only catalog use cases and validated cursors bound to their filters."""

import base64
import binascii
import hashlib
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

from pydantic import Field, ValidationError
from sqlalchemy.orm import Session, sessionmaker

from mastery_backend.domain.content import ContentError, ContentValue
from mastery_backend.domain.content_records import (
    PublicQuestionVersion,
    QuestionListQuery,
    QuestionPage,
)
from mastery_backend.infrastructure.database.catalog_repository import CatalogRepository


class CatalogCursor(ContentValue):
    question_id: UUID
    created_at: datetime
    expires_at: datetime
    filter_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


def filter_digest(query: QuestionListQuery) -> str:
    return hashlib.sha256(
        json.dumps(
            query.model_dump(mode="json", exclude={"cursor", "limit"}), sort_keys=True
        ).encode()
    ).hexdigest()


def decode_cursor(query: QuestionListQuery) -> tuple[datetime, UUID] | None:
    if query.cursor is None:
        return None
    try:
        raw = base64.b64decode(query.cursor, altchars=b"-_", validate=True)
        cursor = CatalogCursor.model_validate_json(raw)
        if cursor.created_at.tzinfo is None or cursor.expires_at.tzinfo is None:
            raise ValueError("timezone missing")
        if cursor.expires_at <= datetime.now(UTC) or cursor.filter_hash != filter_digest(query):
            raise ValueError("cursor no longer valid for these filters")
    except (ValueError, ValidationError, binascii.Error):
        raise ContentError("INVALID_CURSOR", "The catalog cursor is invalid or expired.") from None
    return cursor.created_at, cursor.question_id


class CatalogService:
    def __init__(self, factory: sessionmaker[Session]) -> None:
        self.factory = factory

    def read_question(self, question_id: UUID) -> PublicQuestionVersion:
        with self.factory.begin() as session:
            repository = CatalogRepository(session)
            return repository.public_version(repository.current_version_id(question_id))

    def read_version(self, version_id: UUID) -> PublicQuestionVersion:
        with self.factory.begin() as session:
            return CatalogRepository(session).public_version(version_id)

    def list_questions(self, query: QuestionListQuery) -> QuestionPage:
        after = decode_cursor(query)
        with self.factory.begin() as session:
            repository = CatalogRepository(session)
            identifiers = repository.page_ids(query, after)
            items = repository.public_versions(
                [identifier for identifier, _, _ in identifiers[: query.limit]]
            )
            next_cursor = None
            if len(identifiers) > query.limit:
                _, created_at, question_id = identifiers[query.limit - 1]
                cursor = CatalogCursor(
                    question_id=question_id,
                    created_at=created_at,
                    expires_at=datetime.now(UTC) + timedelta(days=1),
                    filter_hash=filter_digest(query),
                )
                next_cursor = base64.urlsafe_b64encode(cursor.model_dump_json().encode()).decode()
            return QuestionPage(items=items, next_cursor=next_cursor)
