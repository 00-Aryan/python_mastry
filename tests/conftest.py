from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from mastery_backend.api import routes
from mastery_backend.main import create_app
from mastery_backend.settings import Settings


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        database_url="postgresql://test_user:test_password@localhost/mastery_test",
    )


@pytest.fixture
def app(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    monkeypatch.setattr(routes, "check_database_connection", lambda engine: None)
    return create_app(settings)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app, base_url="http://localhost", raise_server_exceptions=False) as client:
        yield client


@pytest.fixture
def complete_draft() -> dict[str, object]:
    return {
        "title": "Echo a word",
        "statement": "Return the supplied word.",
        "track": "python",
        "difficulty": "easy",
        "assessment_role": "assessment",
        "supported_modes": ["assessment", "practice"],
        "suggested_budget_seconds": 600,
        "contract": {
            "function_name": "echo",
            "arguments": [{"name": "word", "type": "string"}],
            "output": {"type": "string"},
            "constraints": ["Word is nonempty"],
            "invalid_input_policy": "not_tested",
        },
        "skill_mappings": [
            {
                "skill_id": "00000000-0000-0000-0000-000000000011",
                "attribution_role": "primary",
                "rubric": {"criterion": "PRIVATE_RUBRIC"},
            }
        ],
        "pattern_ids": ["00000000-0000-0000-0000-000000000021"],
        "examples": [
            {
                "position": 1,
                "input": ["hello"],
                "expected_output": "hello",
                "explanation": "Same word",
            }
        ],
        "test_cases": [
            {
                "position": 1,
                "visibility": "private",
                "input": ["PRIVATE_TEST_INPUT"],
                "expected_output": "PRIVATE_TEST_OUTPUT",
                "critical": True,
            }
        ],
        "assistance_steps": [
            {
                "position": 1,
                "kind": "full_solution",
                "content": "PRIVATE_HINT",
                "next_budget_seconds": 600,
            }
        ],
        "solution": {
            "reference_code": "def echo(word):\n    return word # PRIVATE_SOLUTION",
            "explanation": "Return input",
            "expected_complexity": "O(1)",
        },
    }
