import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict

from mastery_backend.infrastructure.observability.logging import logger, request_id_context
from mastery_backend.main import create_app
from mastery_backend.settings import Settings


@pytest.mark.parametrize("path,status", [("/health/live", "alive"), ("/health/ready", "ready")])
def test_health_is_explicit_about_release(client: TestClient, path: str, status: str) -> None:
    response = client.get(path)
    assert response.status_code == 200
    assert response.json() == {
        "status": status,
        "release_stage": "B6b-local-isolated-runner",
        "database": "connected" if path == "/health/ready" else "not_checked",
        "evaluation": "not_checked" if status == "alive" else "unavailable",
    }
    assert response.headers["cache-control"] == "no-store"


def test_public_config_has_no_secrets_or_fake_capabilities(client: TestClient) -> None:
    response = client.get("/api/v1/config/public")
    assert response.json()["capabilities"] == [
        "attempt_lifecycle",
        "server_timers",
        "progressive_assistance",
        "submission_receipts",
        "evaluation_lifecycle",
    ]
    assert response.json()["attempt_modes"] == ["practice", "assessment"]
    assert "database_url" not in response.text
    assert "test_password" not in response.text


def test_request_id_is_returned_and_context_is_reset(client: TestClient) -> None:
    response = client.get("/health/live", headers={"X-Request-ID": "trace_123"})
    assert response.headers["X-Request-ID"] == "trace_123"
    assert request_id_context.get() is None


@pytest.mark.parametrize("request_id", ["x" * 65, "bad id", "bad/id"])
def test_invalid_request_id_is_replaced(client: TestClient, request_id: str) -> None:
    response = client.get("/health/live", headers={"X-Request-ID": request_id})
    assert response.headers["X-Request-ID"] != request_id
    assert len(response.headers["X-Request-ID"]) == 32


def test_not_found_and_wrong_method_use_error_envelope(client: TestClient) -> None:
    for response in [client.get("/api/v1/recommendations"), client.post("/health/live")]:
        error = response.json()["error"]
        assert error["request_id"] == response.headers["X-Request-ID"]
        assert error["code"] in {"NOT_FOUND", "METHOD_NOT_ALLOWED"}


def test_untrusted_host_is_rejected(client: TestClient) -> None:
    response = client.get("/health/live", headers={"host": "evil.example"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_HOST"


def test_docs_and_openapi_only_describe_released_routes(client: TestClient) -> None:
    assert client.get("/docs").status_code == 200
    schema = client.get("/openapi.json").json()
    assert set(schema["paths"]) == {
        "/api/v1/submissions/{submission_id}/evaluations",
        "/api/v1/evaluations/{job_id}",
        "/api/v1/attempts/{attempt_id}/evaluations",
        "/api/v1/attempts/{attempt_id}/submissions",
        "/api/v1/submissions/{submission_id}",
        "/api/v1/attempts/{attempt_id}/assistance",
        "/api/v1/attempts/{attempt_id}/assistance/next",
        "/api/v1/attempts/{attempt_id}/assistance/solution",
        "/api/v1/attempts",
        "/api/v1/attempts/{attempt_id}",
        "/api/v1/attempts/{attempt_id}/question",
        "/api/v1/attempts/{attempt_id}/pause",
        "/api/v1/attempts/{attempt_id}/resume",
        "/api/v1/attempts/{attempt_id}/extend",
        "/api/v1/attempts/{attempt_id}/defer",
        "/api/v1/attempts/{attempt_id}/abandon",
        "/health/live",
        "/health/ready",
        "/api/v1/config/public",
        "/api/v1/questions",
        "/api/v1/questions/{question_id}",
        "/api/v1/question-versions/{version_id}",
        "/api/v1/admin/questions",
        "/api/v1/admin/questions/{question_id}/versions",
        "/api/v1/admin/question-versions/{version_id}",
        "/api/v1/admin/question-versions/{version_id}/publish",
        "/api/v1/admin/questions/{question_id}/archive",
        "/api/v1/skills",
        "/api/v1/skills/graph",
        "/api/v1/skills/{skill_id}",
        "/api/v1/admin/skills",
        "/api/v1/admin/skills/{skill_id}",
        "/api/v1/admin/skills/{skill_id}/archive",
        "/api/v1/admin/skills/{dependent_id}/prerequisites",
        "/api/v1/admin/skills/{dependent_id}/prerequisites/{prerequisite_id}",
    }
    ids = [
        operation["operationId"] for item in schema["paths"].values() for operation in item.values()
    ]
    assert len(ids) == len(set(ids))


def test_docs_can_be_disabled(settings: Settings) -> None:
    app = create_app(settings.model_copy(update={"api_docs_enabled": False}))
    with TestClient(app, base_url="http://localhost") as client:
        for path in ["/docs", "/redoc", "/openapi.json"]:
            assert client.get(path).status_code == 404


class InputBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    count: int


def register_test_input(app: FastAPI) -> None:
    @app.post("/test-input")
    def test_input(body: InputBody) -> dict[str, int]:
        return {"count": body.count}


def test_malformed_json_and_validation_do_not_echo_input(app: FastAPI, client: TestClient) -> None:
    register_test_input(app)
    invalid = client.post("/test-input", json={"count": "SUPER_SECRET_INPUT"})
    assert invalid.status_code == 422
    assert "SUPER_SECRET_INPUT" not in invalid.text
    malformed = client.post(
        "/test-input", content=b'{"count":', headers={"content-type": "application/json"}
    )
    assert malformed.status_code == 400
    assert malformed.json()["error"]["code"] == "MALFORMED_JSON"
    assert client.post("/test-input", json={"count": 1, "unknown": 2}).status_code == 422


def test_unexpected_exception_is_safe(app: FastAPI, client: TestClient) -> None:
    @app.get("/raise-error")
    def raise_error() -> None:
        raise RuntimeError("private-password")

    response = client.get("/raise-error")
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "private-password" not in response.text
    assert response.headers["X-Request-ID"] == response.json()["error"]["request_id"]


def test_body_size_and_content_type(settings: Settings) -> None:
    app = create_app(
        settings.model_copy(update={"max_request_body_bytes": 20, "max_code_bytes": 10})
    )
    register_test_input(app)
    with TestClient(app, base_url="http://localhost") as client:
        assert client.post("/test-input", json={"count": 1}).status_code == 200
        assert client.post("/test-input", content=b"x" * 21).status_code == 413
        assert (
            client.post(
                "/test-input", content=b"x", headers={"content-type": "text/plain"}
            ).status_code
            == 415
        )
        assert (
            client.post(
                "/test-input", content=b"", headers={"content-length": "not-a-number"}
            ).status_code
            == 400
        )


def test_chunked_body_limit_ignores_missing_length(settings: Settings) -> None:
    app = create_app(
        settings.model_copy(update={"max_request_body_bytes": 20, "max_code_bytes": 10})
    )
    with TestClient(app, base_url="http://localhost") as client:
        response = client.post(
            "/health/live",
            content=iter([b"x" * 10, b"x" * 11]),
            headers={"content-type": "application/json"},
        )
        assert response.status_code == 413


def test_cors_preflight_and_response_headers(settings: Settings) -> None:
    app = create_app(settings.model_copy(update={"allowed_origins": ["http://localhost:5173"]}))
    with TestClient(app, base_url="http://localhost") as client:
        accepted = client.options(
            "/health/live",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "X-Request-ID",
            },
        )
        assert accepted.status_code == 200
        assert accepted.headers["access-control-allow-origin"] == "http://localhost:5173"
        rejected = client.get("/health/live", headers={"Origin": "http://evil.example"})
        assert "access-control-allow-origin" not in rejected.headers
        actual = client.get("/health/live", headers={"Origin": "http://localhost:5173"})
        assert "X-Request-ID" in actual.headers["access-control-expose-headers"]


def test_repeated_app_factory_does_not_duplicate_log_handlers(settings: Settings) -> None:
    create_app(settings)
    before = len(logger.handlers)
    create_app(settings)
    assert len(logger.handlers) == before


@pytest.mark.parametrize("host", ["localhost/path", "user@localhost", "localhost:bad", "[bad"])
def test_malformed_host_is_rejected(client: TestClient, host: str) -> None:
    assert client.get("/health/live", headers={"host": host}).status_code == 400


def test_preflight_cannot_bypass_host_check(client: TestClient) -> None:
    response = client.options(
        "/health/live",
        headers={
            "host": "evil.example",
            "Origin": "http://localhost",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_HOST"


def test_denied_preflight_uses_json_error(client: TestClient) -> None:
    response = client.options(
        "/health/live",
        headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "GET"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "CORS_DENIED"


def test_oversized_content_length_header_is_a_safe_error(client: TestClient) -> None:
    response = client.post("/health/live", content=b"", headers={"content-length": "9" * 5000})
    assert response.status_code == 400


def test_safe_internal_error_is_visible_to_permitted_browser(settings: Settings) -> None:
    app = create_app(settings.model_copy(update={"allowed_origins": ["http://localhost:5173"]}))

    @app.get("/fail")
    def fail() -> None:
        raise ValueError("secret")

    with TestClient(app, base_url="http://localhost", raise_server_exceptions=False) as client:
        allowed = client.get("/fail", headers={"Origin": "http://localhost:5173"})
        assert allowed.status_code == 500
        assert allowed.headers["access-control-allow-origin"] == "http://localhost:5173"
        denied = client.get("/fail", headers={"Origin": "http://evil.example"})
        assert "access-control-allow-origin" not in denied.headers


def test_writes_without_development_identity_are_denied(client: TestClient) -> None:
    response = client.post(
        "/api/v1/admin/questions",
        json={
            "code": "DRAFT",
            "family_id": "00000000-0000-0000-0000-000000000031",
            "draft": {"title": "Draft", "statement": "Statement"},
        },
        headers={
            "Idempotency-Key": "unauthorized",
            "X-User-ID": "00000000-0000-0000-0000-000000000001",
            "X-Role": "content_admin",
        },
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"
