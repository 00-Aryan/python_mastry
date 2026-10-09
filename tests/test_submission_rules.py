"""Source byte boundaries and storage-safe intake never interpret Python."""

import hashlib

import pytest

from mastery_backend.domain.content import ContentError
from mastery_backend.domain.submissions import validate_submission_source


@pytest.mark.parametrize(
    "source", ["return wrong", "def broken(:", "\r\nprint('π')\r\n", "import os; os._exit(1)"]
)
def test_invalid_or_dangerous_python_is_only_hashed(source):
    digest, size = validate_submission_source(source, 100)
    assert digest == hashlib.sha256(source.encode()).hexdigest()
    assert size == len(source.encode())


@pytest.mark.parametrize("source", ["", " \t\r\n", "x\x00", "\ud800"])
def test_unsupported_source_is_safe_validation_error(source):
    with pytest.raises(ContentError) as caught:
        validate_submission_source(source, 100)
    assert caught.value.code == "INVALID_SOURCE"
    assert source not in caught.value.message or source == ""


def test_utf8_byte_limit_not_character_count():
    assert validate_submission_source("ππ", 4)[1] == 4
    with pytest.raises(ContentError) as caught:
        validate_submission_source("ππx", 4)
    assert caught.value.code == "CODE_TOO_LARGE"


def test_completed_attempts_cannot_accept_new_source():
    from mastery_backend.domain.submissions import validate_submission_lifecycle

    with pytest.raises(ContentError) as caught:
        validate_submission_lifecycle("completed")
    assert caught.value.code == "INVALID_ATTEMPT_STATE"
