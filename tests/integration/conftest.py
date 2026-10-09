"""Opt-in real PostgreSQL tests; never target an ordinary application database."""

import os
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import Connection, text
from sqlalchemy.engine import make_url

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
