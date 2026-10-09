"""Verification boundary. No executor is implemented in this storage increment."""

from typing import Protocol

from pydantic import Field

from mastery_backend.domain.content import ContentError, ContentValue


class VerificationProof(ContentValue):
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    verifier_version: str = Field(min_length=1, max_length=100)
    verification_id: str = Field(min_length=1, max_length=200)


class ReferenceVerifier(Protocol):
    def verify(self, immutable_snapshot: bytes, content_hash: str) -> VerificationProof: ...


class UnavailableReferenceVerifier:
    def verify(self, immutable_snapshot: bytes, content_hash: str) -> VerificationProof:
        raise ContentError(
            "VERIFICATION_UNAVAILABLE", "Trusted reference verification is unavailable."
        )
