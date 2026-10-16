"""Capture authoring snapshots, isolate reference runs, then append immutable reports."""

from uuid import UUID, uuid4

from sqlalchemy.orm import Session, sessionmaker

from mastery_backend.application.admin_commands import AdminCommands
from mastery_backend.application.clock import Clock
from mastery_backend.application.content_service import ContentService
from mastery_backend.domain.content import ContentError, content_snapshot, validate_publication
from mastery_backend.domain.identity import Principal
from mastery_backend.domain.publication_artifacts import (
    MAXIMUM_CASES,
    VERIFIER_IDENTITY,
    VERIFIER_VERSION,
    PublicationArtifactSummary,
    bundle_bytes,
    digest,
    reference_evaluator_policy,
    reference_evaluator_policy_id,
    verification_inputs,
)
from mastery_backend.infrastructure.database.content_repository import ContentRepository
from mastery_backend.infrastructure.database.publication_models import (
    PublicationVerificationArtifact,
)
from mastery_backend.infrastructure.database.publication_repository import append_artifact
from mastery_backend.infrastructure.runner.local_sandbox import LocalSandbox
from mastery_backend.infrastructure.runner.reference_quality import grade_quality


class PublicationArtifactService:
    def __init__(self, factory: sessionmaker[Session], clock: Clock, sandbox: LocalSandbox) -> None:
        # This is a separate trusted local command, not an injectable API verifier/runner.
        if type(sandbox) is not LocalSandbox:
            raise ContentError("VERIFICATION_UNAVAILABLE", "Trusted isolation is unavailable.")
        self.factory, self.clock, self.sandbox = factory, clock, sandbox
        self.commands = AdminCommands(factory)

    def verify(
        self, principal: Principal, version_id: UUID, expected_revision: int
    ) -> PublicationArtifactSummary:
        with self.factory.begin() as session:
            self.commands.authorize(session, principal)
            repository = ContentRepository(session)
            version = repository.version(version_id, lock=True)
            ContentService._check_draft(version, expected_revision)
            if repository.question(version.question_id).archived_at is not None:
                raise ContentError("QUESTION_ARCHIVED", "Archived questions cannot be verified.")
            content = repository.content(version)
            validate_publication(content)
            repository.validate_references(content, version.id)
            snapshot = content_snapshot(content)
        # Parse back immutable bytes: no shared mutable authoring collections cross this boundary.
        content = verification_inputs(snapshot)
        assert content.solution is not None and content.contract is not None
        total = len(content.examples) + len(content.test_cases)
        if not 1 <= total <= MAXIMUM_CASES:
            raise ContentError("VERIFICATION_LIMIT", "Verification supports at most 64 cases.")
        policy = reference_evaluator_policy(self.sandbox.image_hash, self.sandbox.profile_hash)
        policy_id = reference_evaluator_policy_id(policy)
        try:
            result, quality = grade_quality(self.sandbox, content)
        finally:
            self.sandbox.cancel()
        summary = PublicationArtifactSummary(
            id=uuid4(),
            question_version_id=version_id,
            revision=expected_revision,
            content_hash=digest(snapshot),
            bundle_hash=digest(bundle_bytes(content)),
            reference_hash=digest(content.solution.reference_code.encode()),
            evaluator_policy_version_id=policy_id,
            verifier_identity=VERIFIER_IDENTITY,
            verifier_version=VERIFIER_VERSION,
            created_at=self.clock.now(),
            result=result,
            quality=quality,
        )
        with self.factory.begin() as session:
            # Revocation during execution denies persistence. Historical bytes may differ from
            # today's draft; S013 must re-lock/recheck them before ever consuming this artifact.
            self.commands.authorize(session, principal)
            # Serialize the new historical FK against draft deletion using existing lock order.
            ContentRepository(session).version(version_id, lock=True)
            append_artifact(
                session,
                PublicationVerificationArtifact(
                    **summary.model_dump(exclude={"result", "quality"}),
                    requested_by=principal.user_id,
                    snapshot_bytes=snapshot,
                    result_json=result.model_dump(),
                ),
                policy.model_dump(),
                quality,
            )
        return summary
