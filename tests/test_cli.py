import pytest
from fastapi import FastAPI

from mastery_backend import cli


def test_launcher_reports_only_invalid_field_names(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "private-invalid-database-secret")
    with pytest.raises(SystemExit) as caught:
        cli.main()
    assert "database_url" in str(caught.value)
    assert "private-invalid" not in str(caught.value)


def test_launcher_uses_validated_host_and_port(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:password@localhost/mastery_test")
    monkeypatch.setenv("API_PORT", "8123")
    recorded: dict[str, object] = {}

    def capture_run(app: FastAPI, **options: object) -> None:
        recorded.update(options)
        assert app.title == "Python Mastery Backend"

    monkeypatch.setattr(cli.uvicorn, "run", capture_run)
    cli.main()
    assert recorded == {"host": "127.0.0.1", "port": 8123, "access_log": False}
