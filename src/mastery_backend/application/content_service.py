"""Question use cases own transactions, revision checks and durable command replay."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from mastery_backend.application.admin_commands import AdminCommands, CommandResult
from mastery_backend.application.publication_verification import ReferenceVerifier
from mastery_backend.domain.content import (
    ContentError,
    DraftContent,
    content_digest,
    content_snapshot,
    validate_publication,
)
from mastery_backend.domain.content_records import AdminQuestionVersion, QuestionLifecycle
from mastery_backend.domain.identity import Principal
from mastery_backend.infrastructure.database.content_models import (
    Question,
    QuestionFamily,
    QuestionVersion,
)
from mastery_backend.infrastructure.database.content_repository import ContentRepository


class ContentService:
    def __init__(self, factory: sessionmaker[Session], verifier: ReferenceVerifier) -> None:
        self.factory = factory
        self.verifier = verifier
        self.commands = AdminCommands(factory)

    @staticmethod
    def _check_draft(version: QuestionVersion, expected_revision: int) -> None:
        if version.status != "draft":
            raise ContentError(
                "PUBLISHED_IMMUTABLE", "Published content cannot be edited or deleted."
            )
        if version.revision != expected_revision:
            raise ContentError("STALE_REVISION", "The draft changed; reload before retrying.")

    @staticmethod
    def _snapshot(repository: ContentRepository, version: QuestionVersion) -> AdminQuestionVersion:
        question = repository.question(version.question_id)
        return AdminQuestionVersion.model_validate(
            {
                **repository.content(version).model_dump(),
                "id": version.id,
                "question_id": version.question_id,
                "code": question.code,
                "version_number": version.version_number,
                "revision": version.revision,
                "question_revision": question.revision,
                "status": version.status,
                "published_at": version.published_at,
                "archived_at": question.archived_at,
            }
        )

    def create_question(
        self, principal: Principal, key: str, code: str, family_id: UUID, content: DraftContent
    ) -> CommandResult:
        def create(session: Session) -> CommandResult:
            repository = ContentRepository(session)
            if session.get(QuestionFamily, family_id) is None:
                raise ContentError("INVALID_FAMILY", "Question family does not exist.")
            repository.validate_references(content)
            question = Question(code=code, family_id=family_id)
            session.add(question)
            session.flush()
            version = repository.next_version(question, content)
            snapshot = self._snapshot(repository, version)
            return CommandResult(
                snapshot.model_dump(mode="json"),
                201,
                f"/api/v1/admin/question-versions/{version.id}",
            )

        return self.commands.run(
            principal,
            "POST /api/v1/admin/questions",
            key,
            {"code": code, "family_id": str(family_id), "draft": content.model_dump(mode="json")},
            create,
        )

    def create_version(
        self, principal: Principal, key: str, question_id: UUID, content: DraftContent
    ) -> CommandResult:
        def create(session: Session) -> CommandResult:
            repository = ContentRepository(session)
            question = repository.question(question_id, lock=True)
            if question.archived_at is not None:
                raise ContentError(
                    "QUESTION_ARCHIVED", "Archived questions cannot accept new drafts."
                )
            repository.validate_references(content)
            version = repository.next_version(question, content)
            return CommandResult(
                self._snapshot(repository, version).model_dump(mode="json"),
                201,
                f"/api/v1/admin/question-versions/{version.id}",
            )

        return self.commands.run(
            principal,
            f"POST /api/v1/admin/questions/{question_id}/versions",
            key,
            content.model_dump(mode="json"),
            create,
        )

    def read_admin_version(self, principal: Principal, version_id: UUID) -> AdminQuestionVersion:
        with self.factory.begin() as session:
            self.commands.authorize(session, principal)
            repository = ContentRepository(session)
            return self._snapshot(repository, repository.version(version_id))

    def patch_draft(
        self,
        principal: Principal,
        version_id: UUID,
        expected_revision: int,
        changes: dict[str, Any],
    ) -> AdminQuestionVersion:
        try:
            with self.factory.begin() as session:
                self.commands.authorize(session, principal)
                repository = ContentRepository(session)
                version = repository.version(version_id, lock=True)
                self._check_draft(version, expected_revision)
                if repository.question(version.question_id).archived_at is not None:
                    raise ContentError("QUESTION_ARCHIVED", "Archived questions cannot be edited.")
                try:
                    content = DraftContent.model_validate(
                        {**repository.content(version).model_dump(), **changes}
                    )
                except ValidationError:
                    raise ContentError("INVALID_DRAFT", "The resulting draft is invalid.") from None
                repository.validate_references(content, version.id)
                repository.replace_content(version, content)
                version.revision += 1
                session.flush()
                return self._snapshot(repository, version)
        except IntegrityError:
            raise ContentError(
                "CONTENT_CONFLICT", "The draft conflicts with a database constraint."
            ) from None

    def delete_draft(self, principal: Principal, version_id: UUID, expected_revision: int) -> None:
        with self.factory.begin() as session:
            self.commands.authorize(session, principal)
            repository = ContentRepository(session)
            version = repository.version(version_id, lock=True)
            self._check_draft(version, expected_revision)
            repository.delete_draft(version)

    def archive_question(
        self, principal: Principal, key: str, question_id: UUID, expected_revision: int
    ) -> CommandResult:
        def archive(session: Session) -> CommandResult:
            repository = ContentRepository(session)
            question = repository.question(question_id, lock=True)
            if question.revision != expected_revision:
                raise ContentError(
                    "STALE_REVISION", "The question changed; reload before retrying."
                )
            if question.archived_at is not None:
                raise ContentError("QUESTION_ARCHIVED", "The question is already archived.")
            question.archived_at = datetime.now(UTC)
            question.revision += 1
            return CommandResult(
                QuestionLifecycle(
                    id=question.id, revision=question.revision, archived_at=question.archived_at
                ).model_dump(mode="json")
            )

        return self.commands.run(
            principal,
            f"POST /api/v1/admin/questions/{question_id}/archive",
            key,
            {"expected_revision": expected_revision},
            archive,
        )

    def publish_version(
        self, principal: Principal, key: str, version_id: UUID, expected_revision: int
    ) -> CommandResult:
        operation = f"POST /api/v1/admin/question-versions/{version_id}/publish"
        payload = {"expected_revision": expected_revision}
        # Snapshot then release all locks/connections before invoking an external verifier.
        with self.factory.begin() as session:
            self.commands.authorize(session, principal)
            replay = self.commands.replay(
                session, principal, operation, key, self.commands.request_hash(payload)
            )
            if replay is not None:
                return replay
            repository = ContentRepository(session)
            version = repository.version(version_id, lock=True)
            self._check_draft(version, expected_revision)
            content = repository.content(version)
            validate_publication(content)
            repository.validate_references(content, version.id)
            if repository.question(version.question_id).archived_at is not None:
                raise ContentError("QUESTION_ARCHIVED", "Archived questions cannot be published.")
        digest = content_digest(content)
        proof = self.verifier.verify(content_snapshot(content), digest)
        if proof.content_hash != digest:
            raise ContentError("VERIFICATION_MISMATCH", "Verification does not match this content.")

        def publish(session: Session) -> CommandResult:
            repository = ContentRepository(session)
            version = repository.version(version_id, lock=True)
            self._check_draft(version, expected_revision)
            current = repository.content(version)
            if content_digest(current) != digest:
                raise ContentError("STALE_REVISION", "Content changed during verification.")
            validate_publication(current)
            repository.validate_references(current, version.id)
            if repository.question(version.question_id).archived_at is not None:
                raise ContentError("QUESTION_ARCHIVED", "Archived questions cannot be published.")
            version.status = "published"
            version.published_at = datetime.now(UTC)
            version.verification_json = proof.model_dump(mode="json")
            version.revision += 1
            session.flush()
            return CommandResult(self._snapshot(repository, version).model_dump(mode="json"))

        return self.commands.run(principal, operation, key, payload, publish)
