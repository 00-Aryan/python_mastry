"""Canonical reference-verification inputs and bounded, private-value-free results."""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import Field, model_validator

from mastery_backend.domain.content import (
    ContentError,
    ContentValue,
    DraftContent,
    content_snapshot,
)
from mastery_backend.domain.evaluations import EvaluationPolicy, Outcome
from mastery_backend.domain.question_quality import QualityCheckResult

VERIFIER_IDENTITY = "local-reference-verifier"
VERIFIER_VERSION = "quality-v2"
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
    quality: QualityCheckResult | None = None


REPORT_MAX_AGE_SECONDS = 86400


@dataclass(frozen=True)
class PublicationSnapshot:
    question_version_id: UUID
    revision: int
    immutable_snapshot: bytes
    content_hash: str


def reference_evaluator_policy(image_hash: str, profile_hash: str) -> EvaluationPolicy:
    return EvaluationPolicy(
        protocol_version=2,
        runtime_image_hash=image_hash,
        isolation_profile_hash=profile_hash,
        maximum_dispatches=1,
        lease_seconds=30,
        deadline_seconds=30,
        backoff_seconds=5,
    )


def reference_evaluator_policy_id(policy: EvaluationPolicy) -> UUID:
    return uuid5(
        NAMESPACE_URL, "publication-quality-v2:" + digest(policy.model_dump_json().encode())
    )


def validate_publication_artifact(
    report: PublicationArtifactSummary,
    stored_snapshot: bytes,
    expected: PublicationSnapshot,
    approved_policy_id: UUID,
    policy: EvaluationPolicy,
    now: datetime,
) -> None:
    if report.verifier_version == "reference-v1":
        raise ContentError("VERIFICATION_UNAVAILABLE", "Fresh quality verification is required.")
    if report.verifier_identity != VERIFIER_IDENTITY or report.verifier_version != VERIFIER_VERSION:
        raise ContentError("VERIFICATION_MISMATCH", "Unsupported reference verifier.")
    if (
        report.evaluator_policy_version_id != approved_policy_id
        or policy.protocol_version != 2
        or policy.runtime_image_hash is None
        or policy.isolation_profile_hash is None
        or policy
        != reference_evaluator_policy(policy.runtime_image_hash, policy.isolation_profile_hash)
        or reference_evaluator_policy_id(policy) != approved_policy_id
    ):
        raise ContentError(
            "VERIFICATION_UNAVAILABLE", "An approved verifier policy is unavailable."
        )
    if report.question_version_id != expected.question_version_id:
        raise ContentError("VERIFICATION_MISMATCH", "Verification belongs to another version.")
    if report.revision != expected.revision:
        raise ContentError(
            "VERIFICATION_STALE", "Verify the current draft revision before publishing."
        )
    content = verification_inputs(stored_snapshot)
    if (
        stored_snapshot != expected.immutable_snapshot
        or digest(stored_snapshot) != report.content_hash
        or report.content_hash != expected.content_hash
        or content.solution is None
        or report.bundle_hash != digest(bundle_bytes(content))
        or report.reference_hash != digest(content.solution.reference_code.encode())
        or report.result.total_cases != len(content.examples) + len(content.test_cases)
    ):
        raise ContentError("VERIFICATION_MISMATCH", "Verification does not match this content.")
    if report.quality is None:
        raise ContentError("VERIFICATION_UNAVAILABLE", "Quality verification is unavailable.")
    if report.quality.total_candidates != len(content.incorrect_solutions):
        raise ContentError("VERIFICATION_MISMATCH", "Quality evidence does not match this content.")
    age = (now - report.created_at).total_seconds()
    if not 0 <= age < REPORT_MAX_AGE_SECONDS:
        raise ContentError("VERIFICATION_STALE", "Reference verification expired; verify again.")
    if (
        report.result.outcome == "infrastructure_error"
        or report.quality.reason_code == "INFRASTRUCTURE_ERROR"
    ):
        raise ContentError(
            "VERIFICATION_UNAVAILABLE", "Trusted reference verification is unavailable."
        )
    if report.result.outcome != "passed" or report.quality.reason_code != "PASSED":
        raise ContentError(
            "VERIFICATION_FAILED", "Reference verification failed; revise and verify again."
        )
