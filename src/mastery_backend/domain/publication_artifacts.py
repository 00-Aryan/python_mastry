"""Canonical reference-verification inputs and bounded, private-value-free results."""

import hashlib
import json
from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import Field, model_validator

from mastery_backend.domain.content import (
    ContentError,
    ContentValue,
    DraftContent,
    content_snapshot,
)
from mastery_backend.domain.evaluations import Outcome

VERIFIER_IDENTITY = "local-reference-verifier"
VERIFIER_VERSION = "reference-v1"
MAXIMUM_CASES = 64
MAXIMUM_SNAPSHOT_BYTES = 1048576
Hash = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def verification_inputs(snapshot: bytes) -> DraftContent:
    if len(snapshot) > MAXIMUM_SNAPSHOT_BYTES:
        raise ContentError("VERIFICATION_LIMIT", "Verification snapshot exceeds one MiB.")
    content = DraftContent.model_validate_json(snapshot)
    if content_snapshot(content) != snapshot:
        raise ContentError("VERIFICATION_MISMATCH", "Verification requires canonical content.")
    return content


def bundle_bytes(content: DraftContent) -> bytes:
    # Pin the exact authored bundle, including visibility, positions and comparison rules.
    return json.dumps(
        {
            "examples": [case.model_dump(mode="json") for case in content.examples],
            "tests": [case.model_dump(mode="json") for case in content.test_cases],
        },
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()


class ReferenceCheckResult(ContentValue):
    outcome: Outcome
    checked_cases: int = Field(ge=0, le=MAXIMUM_CASES)
    total_cases: int = Field(ge=1, le=MAXIMUM_CASES)

    @model_validator(mode="after")
    def validate_counts(self) -> "ReferenceCheckResult":
        if self.checked_cases > self.total_cases or (
            self.outcome == "passed" and self.checked_cases != self.total_cases
        ):
            raise ValueError("Result counts do not match outcome")
        return self


class PublicationArtifactSummary(ContentValue):
    id: UUID
    question_version_id: UUID
    revision: int
    content_hash: Hash
    bundle_hash: Hash
    reference_hash: Hash
    evaluator_policy_version_id: UUID
    verifier_identity: str
    verifier_version: str
    created_at: datetime
    result: ReferenceCheckResult
