"""Receipt input rejects client ownership, clocks and success claims."""

from pydantic import Field

from mastery_backend.api.schemas.attempts import AttemptRevision
from mastery_backend.domain.submissions import SubmissionPurpose


class AcceptSubmission(AttemptRevision):
    source_code: str = Field(
        strict=True,
        description="Exact UTF-8 Python source, bounded by MAX_CODE_BYTES; not executed.",
    )
    purpose: SubmissionPurpose
