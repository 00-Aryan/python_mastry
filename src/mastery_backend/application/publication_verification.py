"""Publication evidence boundary; implementations never execute code in the API."""

from typing import Protocol

from pydantic import Field
from sqlalchemy.orm import Session

from mastery_backend.domain.content import ContentError, ContentValue
from mastery_backend.domain.publication_artifacts import PublicationSnapshot


class VerificationProof(ContentValue):
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    verifier_version: str = Field(min_length=1, max_length=100)
    verification_id: str = Field(min_length=1, max_length=200)


class ReferenceVerifier(Protocol):
    def verify(self, snapshot: PublicationSnapshot) -> VerificationProof: ...

    def recheck(
        self, session: Session, snapshot: PublicationSnapshot, proof: VerificationProof
    ) -> None: ...


class UnavailableReferenceVerifier:
    def verify(self, snapshot: PublicationSnapshot) -> VerificationProof:
        raise ContentError(
            "VERIFICATION_UNAVAILABLE", "Trusted reference verification is unavailable."
        )

    def recheck(
        self, session: Session, snapshot: PublicationSnapshot, proof: VerificationProof
    ) -> None:
        self.verify(snapshot)
