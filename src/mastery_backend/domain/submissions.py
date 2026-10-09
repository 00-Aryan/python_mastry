"""Receipt intake rules; learner source is never interpreted here."""

import hashlib
from typing import Literal

from mastery_backend.domain.content import ContentError
from mastery_backend.domain.timer_policy import Lifecycle

SubmissionPurpose = Literal["public_run", "assessment"]


def validate_submission_source(source_code: str, maximum_code_bytes: int) -> tuple[str, int]:
    try:
        source_bytes = source_code.encode("utf-8")
    except UnicodeEncodeError:
        raise ContentError("INVALID_SOURCE", "Source must be valid UTF-8 text.") from None
    if len(source_bytes) > maximum_code_bytes:
        raise ContentError("CODE_TOO_LARGE", "Source exceeds MAX_CODE_BYTES.")
    if "\x00" in source_code or not source_code.strip():
        raise ContentError("INVALID_SOURCE", "Supply nonblank source without NUL characters.")
    return hashlib.sha256(source_bytes).hexdigest(), len(source_bytes)


def validate_submission_lifecycle(lifecycle: Lifecycle) -> None:
    if lifecycle not in {"active", "paused"}:
        raise ContentError(
            "INVALID_ATTEMPT_STATE", "Only active or paused attempts accept submissions."
        )
