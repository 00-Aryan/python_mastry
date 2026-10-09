from io import StringIO
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config


def test_offline_migration_sql_has_no_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:private-password@localhost/mastery")
    output = StringIO()
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"), output_buffer=output)
    command.upgrade(config, "head", sql=True)
    sql = output.getvalue()
    assert "CREATE TABLE alembic_version" in sql
    assert "PRIMARY KEY" in sql
    assert "0001_database_baseline" in sql
    assert "private-password" not in sql


def test_migration_invalid_configuration_is_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "private-invalid-url")
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    with pytest.raises(SystemExit) as caught:
        command.upgrade(config, "head")
    assert "configuration" in str(caught.value)
    assert "private-invalid-url" not in str(caught.value)
