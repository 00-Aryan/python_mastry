from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from conftest import configured_application_database_url, validate_test_database_url
from fastapi.testclient import TestClient
from sqlalchemy import Connection, inspect, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from mastery_backend.main import create_app
from mastery_backend.settings import Settings


@pytest.mark.parametrize(
    "test_url,application_url",
    [
        ("postgresql://localhost/mastery", None),
        ("postgresql://test:secret@127.0.0.1/mastery_test", "postgresql://localhost/mastery_test"),
    ],
)
def test_unsafe_test_database_is_rejected(test_url: str, application_url: str | None) -> None:
    with pytest.raises(ValueError):
        validate_test_database_url(test_url, application_url)


def test_test_database_guard_reads_application_dotenv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    (tmp_path / ".env").write_text("DATABASE_URL=postgresql://localhost/mastery_test\n")
    with pytest.raises(ValueError, match="must differ"):
        validate_test_database_url(
            "postgresql://localhost/mastery_test", configured_application_database_url()
        )


def test_migration_upgrade_replay_and_downgrade(database_connection: Connection) -> None:
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    config.attributes["connection"] = database_connection
    command.upgrade(config, "0001_database_baseline")
    assert inspect(database_connection).get_table_names() == ["alembic_version"]
    assert database_connection.scalar(text("SELECT version_num FROM alembic_version")) == (
        "0001_database_baseline"
    )
    database_connection.commit()
    command.upgrade(config, "0001_database_baseline")
    assert database_connection.scalar(text("SELECT count(*) FROM alembic_version")) == 1
    database_connection.commit()
    with pytest.raises(IntegrityError), database_connection.begin():
        database_connection.execute(
            text("INSERT INTO alembic_version VALUES ('0001_database_baseline')")
        )
    command.downgrade(config, "base")
    assert database_connection.scalar(text("SELECT count(*) FROM alembic_version")) == 0
    database_connection.commit()
    command.upgrade(config, "0001_database_baseline")
    assert database_connection.scalar(text("SELECT count(*) FROM alembic_version")) == 1
    database_connection.commit()


def test_session_transactions_and_connection_policy(database_connection: Connection) -> None:
    assert database_connection.scalar(text("SHOW timezone")) == "UTC"
    assert database_connection.scalar(text("SHOW statement_timeout")) == "5s"
    database_connection.execute(text("CREATE TABLE transaction_probe (value integer NOT NULL)"))
    database_connection.commit()
    with Session(database_connection) as session:
        session.execute(text("INSERT INTO transaction_probe VALUES (1)"))
        # Closing is not a commit.
    assert database_connection.scalar(text("SELECT count(*) FROM transaction_probe")) == 0
    database_connection.commit()
    with Session(database_connection) as session, session.begin():
        session.execute(text("INSERT INTO transaction_probe VALUES (2)"))
    assert database_connection.scalar(text("SELECT value FROM transaction_probe")) == 2
    database_connection.commit()
    with pytest.raises(RuntimeError), Session(database_connection) as session, session.begin():
        session.execute(text("INSERT INTO transaction_probe VALUES (3)"))
        raise RuntimeError("abort use case")
    assert database_connection.scalar(text("SELECT count(*) FROM transaction_probe")) == 1
    database_connection.commit()
    with pytest.raises(OperationalError), database_connection.begin():
        database_connection.execute(text("SET LOCAL statement_timeout = 1"))
        database_connection.execute(text("SELECT pg_sleep(0.1)"))
    assert database_connection.scalar(text("SELECT 1")) == 1


def test_real_database_readiness(database_connection: Connection) -> None:
    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url=database_connection.engine.url.render_as_string(hide_password=False),
    )
    with TestClient(create_app(settings), base_url="http://localhost") as client:
        response = client.get("/health/ready")
        assert response.status_code == 200
        assert response.json()["database"] == "connected"
