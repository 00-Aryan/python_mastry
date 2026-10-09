import pytest
from pydantic import ValidationError

from mastery_backend.settings import Settings

DATABASE_URL = "postgresql://user:do-not-leak@localhost/mastery_test"


def make_settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, database_url=DATABASE_URL, **overrides)


def test_database_url_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


@pytest.mark.parametrize("url", ["sqlite:///file.db", "postgresql://localhost", "secret"])
def test_invalid_database_url_is_rejected_without_exposure(url: str) -> None:
    with pytest.raises(ValidationError) as caught:
        Settings(_env_file=None, database_url=url)
    assert "input_value" not in str(caught.value)


def test_secret_is_redacted_in_settings_representation() -> None:
    assert "do-not-leak" not in repr(make_settings())


@pytest.mark.parametrize("port", [0, 65536])
def test_invalid_ports(port: int) -> None:
    with pytest.raises(ValidationError):
        make_settings(api_port=port)


@pytest.mark.parametrize(
    "origin",
    [
        "*",
        "http://localhost:5173/",
        "http://u:p@localhost",
        "ftp://localhost",
        "http://localhost:bad",
    ],
)
def test_invalid_origins(origin: str) -> None:
    with pytest.raises(ValidationError):
        make_settings(allowed_origins=[origin])


def test_origin_deduplication() -> None:
    assert make_settings(allowed_origins=["http://localhost:5173"] * 2).allowed_origins == [
        "http://localhost:5173"
    ]


@pytest.mark.parametrize("hosts", [[], ["*"], ["localhost:8000"], ["https://example.com"]])
def test_invalid_allowed_hosts(hosts: list[str]) -> None:
    with pytest.raises(ValidationError):
        make_settings(allowed_hosts=hosts)


def test_code_limit_cannot_exceed_body_limit() -> None:
    with pytest.raises(ValidationError):
        make_settings(max_code_bytes=101, max_request_body_bytes=100)


@pytest.mark.parametrize("overrides", [{"app_env": "production"}, {"auth_mode": "session"}])
def test_unimplemented_hosted_auth_is_rejected(overrides: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        make_settings(**overrides)


def test_environment_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL)
    monkeypatch.setenv("ALLOWED_ORIGINS", '["http://localhost:5173"]')
    monkeypatch.setenv("API_PORT", "8123")
    result = Settings(_env_file=None)
    assert result.allowed_origins == ["http://localhost:5173"]
    assert result.api_port == 8123
