"""Opt-in real PostgreSQL tests; never target an ordinary application database."""

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from mastery_backend.infrastructure.database.session import create_database_engine
from mastery_backend.settings import Settings


def validate_test_database_url(test_url: str, application_url: str | None) -> Settings:
    settings = Settings(_env_file=None, app_env="test", database_url=test_url)
    target = make_url(test_url)
    if not target.database or not target.database.endswith("_test"):
        raise ValueError("TEST_DATABASE_URL must name a database ending in _test")
    # Conservatively reject equal names even across host aliases or credentials.
    if application_url and target.database == make_url(application_url).database:
        raise ValueError("TEST_DATABASE_URL must differ from DATABASE_URL")
    return settings


def configured_application_database_url() -> str | None:
    if os.environ.get("DATABASE_URL") is not None or Path(".env").exists():
        # The normal application also loads .env; guard that target, not just exports.
        return Settings().database_url.get_secret_value()
    return None


@pytest.fixture
def database_connection() -> Iterator[Connection]:
    test_url = os.environ.get("TEST_DATABASE_URL")
    if not test_url:
        pytest.skip("Set TEST_DATABASE_URL to a separate PostgreSQL database ending in _test")
    settings = validate_test_database_url(test_url, configured_application_database_url())
    engine = create_database_engine(settings)
    schema_name = "integration_" + uuid4().hex
    try:
        with engine.connect() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema_name}"'))
            connection.execute(text(f'SET search_path TO "{schema_name}"'))
            connection.commit()
            try:
                yield connection
            finally:
                connection.rollback()
                connection.execute(text(f'DROP SCHEMA "{schema_name}" CASCADE'))
                connection.commit()
    finally:
        engine.dispose()


@pytest.fixture
def storage_factory(database_connection: Connection) -> Iterator[sessionmaker[Session]]:
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import event
    from sqlalchemy.orm import sessionmaker

    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    config.attributes["connection"] = database_connection
    command.upgrade(config, "head")
    schema_name = database_connection.scalar(text("SELECT current_schema()"))
    database_connection.commit()
    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url=database_connection.engine.url.render_as_string(hide_password=False),
    )
    engine = create_database_engine(settings)

    @event.listens_for(engine, "connect")
    def set_test_schema(dbapi_connection: Any, connection_record: object) -> None:
        with dbapi_connection.cursor() as cursor:
            cursor.execute(f'SET search_path TO "{schema_name}"')
        dbapi_connection.commit()

    try:
        yield sessionmaker(bind=engine, expire_on_commit=False)
    finally:
        engine.dispose()


@pytest.fixture
def seeded_storage(storage_factory: sessionmaker[Session]) -> sessionmaker[Session]:
    from uuid import UUID

    from mastery_backend.application.content_seed_service import (
        seed_development_identity,
        seed_reference_catalog,
    )
    from mastery_backend.domain.content_seed import ReferenceCatalogSeed

    seed_development_identity(
        storage_factory,
        UUID("00000000-0000-0000-0000-000000000001"),
        "Test administrator",
        {"learner", "content_admin"},
    )
    seed_reference_catalog(
        storage_factory,
        UUID("00000000-0000-0000-0000-000000000001"),
        ReferenceCatalogSeed.model_validate(
            {
                "curricula": [
                    {
                        "id": "00000000-0000-0000-0000-000000000010",
                        "code": "PYTHON",
                        "title": "Python",
                    }
                ],
                "skills": [
                    {
                        "id": "00000000-0000-0000-0000-000000000011",
                        "curriculum_id": "00000000-0000-0000-0000-000000000010",
                        "code": "PY-ECHO",
                        "title": "Echo",
                        "competency": "Return input",
                    }
                ],
                "patterns": [
                    {
                        "id": "00000000-0000-0000-0000-000000000021",
                        "code": "RETURN",
                        "title": "Return",
                    }
                ],
                "question_families": [
                    {
                        "id": "00000000-0000-0000-0000-000000000031",
                        "code": "ECHO",
                        "novelty_definition": "Identity function",
                    }
                ],
            }
        ),
    )
    return storage_factory


@pytest.fixture
def storage_client(
    seeded_storage: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    from uuid import UUID

    from fastapi.testclient import TestClient

    from mastery_backend import main

    monkeypatch.setattr(main, "create_database_engine", lambda settings: seeded_storage.kw["bind"])
    monkeypatch.setattr(main, "create_session_factory", lambda engine: seeded_storage)
    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url="postgresql://localhost/mastery_test",
        development_user_id=UUID("00000000-0000-0000-0000-000000000001"),
    )
    with TestClient(
        main.create_app(settings), base_url="http://localhost", raise_server_exceptions=False
    ) as client:
        yield client
