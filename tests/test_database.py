from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.exc import OperationalError, TimeoutError

from mastery_backend.api import routes
from mastery_backend.infrastructure.database.session import (
    create_database_engine,
    create_session_factory,
)
from mastery_backend.settings import Settings


def test_engine_is_lazy_and_sessions_are_independent(settings: Settings) -> None:
    engine = create_database_engine(settings)
    try:
        assert engine.url.drivername == "postgresql+psycopg"
        assert engine.pool.size() == 5  # type: ignore[attr-defined]
        factory = create_session_factory(engine)
        with factory() as first, factory() as second:
            assert first is not second
            assert first.get_bind() is engine
            assert not first.in_transaction()
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "field,value",
    [
        ("db_pool_size", 0),
        ("db_max_overflow", -1),
        ("db_pool_timeout_seconds", 0),
        ("db_connect_timeout_seconds", 61),
        ("db_statement_timeout_ms", 0),
    ],
)
def test_database_limits_are_validated(field: str, value: int) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_url="postgresql://localhost/test", **{field: value})


@pytest.mark.parametrize(
    "url",
    ["postgresql://localhost:bad/test", "postgresql://localhost/test?options=unsafe"],
)
def test_database_url_cannot_override_connection_policy(url: str) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_url=url)


def test_database_outage_is_safe_and_liveness_survives(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    failure = OperationalError("secret SQL", {}, Exception("private-password"))
    monkeypatch.setattr(routes, "check_database_connection", Mock(side_effect=failure))
    response = client.get("/health/ready", headers={"X-Request-ID": "db_failure"})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DATABASE_UNAVAILABLE"
    assert response.json()["error"]["request_id"] == "db_failure"
    assert "private-password" not in response.text
    assert "secret SQL" not in response.text
    assert client.get("/health/live").status_code == 200
    monkeypatch.setattr(routes, "check_database_connection", lambda engine: None)
    assert client.get("/health/ready").json()["database"] == "connected"


def test_lifespan_disposes_engine(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    from mastery_backend import main

    engine = create_database_engine(settings)
    dispose = Mock(wraps=engine.dispose)
    monkeypatch.setattr(engine, "dispose", dispose)
    monkeypatch.setattr(main, "create_database_engine", lambda configuration: engine)
    with TestClient(main.create_app(settings), base_url="http://localhost") as client:
        assert client.get("/health/live").status_code == 200
        dispose.assert_not_called()
    dispose.assert_called_once()


@pytest.mark.parametrize(
    "failure",
    [
        OperationalError("PRIVATE_TEST_INPUT", {}, Exception("PRIVATE_SOLUTION")),
        TimeoutError("PRIVATE_SOLUTION"),
    ],
)
def test_database_faults_return_safe_api_errors(
    app: FastAPI,
    client: TestClient,
    failure: Exception,
) -> None:
    @app.get("/test-database-fault")
    def fail_connection() -> None:
        raise failure

    response = client.get("/test-database-fault", headers={"X-Request-ID": "safe-db-fault"})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DATABASE_UNAVAILABLE"
    assert response.json()["error"]["request_id"] == "safe-db-fault"
    assert "PRIVATE_TEST_INPUT" not in response.text
    assert "PRIVATE_SOLUTION" not in response.text
