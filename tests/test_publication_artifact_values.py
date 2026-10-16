"""Input bounds and schema guarantees do not need an executor or a database."""

import pytest
from pydantic import ValidationError

from mastery_backend.application.publication_artifact_service import PublicationArtifactService
from mastery_backend.domain.content import ContentError, DraftContent, content_snapshot
from mastery_backend.domain.publication_artifacts import (
    MAXIMUM_SNAPSHOT_BYTES,
    ReferenceCheckResult,
    bundle_bytes,
    digest,
    verification_inputs,
)


def test_canonical_snapshot_and_private_component_pins(complete_draft):
    content = DraftContent.model_validate(complete_draft)
    snapshot = content_snapshot(content)
    assert verification_inputs(snapshot) == content
    changed = content.model_copy(update={"title": "Changed"})
    assert digest(snapshot) != digest(content_snapshot(changed))
    assert bundle_bytes(content) == bundle_bytes(changed)
    with pytest.raises(ContentError, match="canonical"):
        verification_inputs(b" " + snapshot)
    with pytest.raises(ContentError, match="one MiB"):
        verification_inputs(b"x" * (MAXIMUM_SNAPSHOT_BYTES + 1))


@pytest.mark.parametrize(
    "changes", [{"checked_cases": 65}, {"total_cases": 0}, {"output": "PRIVATE"}]
)
def test_results_are_bounded_and_cannot_carry_diagnostics(changes):
    with pytest.raises(ValidationError):
        ReferenceCheckResult.model_validate(
            {"outcome": "passed", "checked_cases": 1, "total_cases": 1, **changes}
        )


def test_arbitrary_adapter_cannot_be_installed():
    with pytest.raises(ContentError, match="isolation"):
        PublicationArtifactService(None, None, object())
