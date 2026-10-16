"""Validated infrastructure configuration; learning policies do not live here."""

from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)

    app_env: Literal["development", "test", "production"] = "development"
    database_url: SecretStr
    db_pool_size: int = Field(default=5, ge=1, le=100)
    db_max_overflow: int = Field(default=5, ge=0, le=100)
    db_pool_timeout_seconds: int = Field(default=5, ge=1, le=60)
    db_connect_timeout_seconds: int = Field(default=5, ge=1, le=60)
    db_statement_timeout_ms: int = Field(default=5000, ge=1, le=60000)
    local_runner_enabled: bool = False
    publication_evaluator_policy_version_id: UUID | None = None
    auth_mode: Literal["development_identity", "session"] = "development_identity"
    development_user_id: UUID | None = None
    api_host: str = "127.0.0.1"
    api_port: int = Field(default=8000, ge=1, le=65535)
    allowed_origins: list[str] = Field(default_factory=list)
    allowed_hosts: list[str] = Field(default_factory=lambda: ["localhost", "127.0.0.1"])
    cors_allow_credentials: bool = True
    api_docs_enabled: bool | None = None
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    max_request_body_bytes: int = Field(default=262144, ge=1, le=1048576)
    max_code_bytes: int = Field(default=65536, ge=1)
    max_page_size: int = Field(default=100, ge=1, le=100)

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: SecretStr) -> SecretStr:
        url = urlsplit(value.get_secret_value())
        if url.scheme not in {"postgresql", "postgresql+psycopg"} or not url.hostname:
            raise ValueError("DATABASE_URL must identify a PostgreSQL server")
        if not url.path or url.path == "/":
            raise ValueError("DATABASE_URL must include a database name")
        _ = url.port
        if url.query or url.fragment:
            raise ValueError("DATABASE_URL query options and fragments are not supported")
        return value

    @field_validator("allowed_origins")
    @classmethod
    def validate_origins(cls, values: list[str]) -> list[str]:
        for value in values:
            url = urlsplit(value)
            if (
                url.scheme not in {"http", "https"}
                or not url.hostname
                or url.username
                or url.password
                or url.path
                or url.query
                or url.fragment
            ):
                raise ValueError("ALLOWED_ORIGINS requires exact HTTP origins")
            _ = url.port  # Reject invalid ports without accepting partial origins.
        return list(dict.fromkeys(values))

    @field_validator("allowed_hosts")
    @classmethod
    def validate_hosts(cls, values: list[str]) -> list[str]:
        if not values or any(not host or any(char in host for char in "*/:@ ") for host in values):
            raise ValueError("ALLOWED_HOSTS requires exact hostnames without ports")
        return list(dict.fromkeys(host.lower() for host in values))

    @model_validator(mode="after")
    def validate_release_boundaries(self) -> "Settings":
        if self.max_code_bytes > self.max_request_body_bytes:
            raise ValueError("MAX_CODE_BYTES cannot exceed MAX_REQUEST_BODY_BYTES")
        if self.app_env == "production":
            raise ValueError("B0 is local-only; deployed authentication is not implemented")
        if self.auth_mode != "development_identity":
            raise ValueError("Session authentication is not implemented in B0")
        if self.development_user_id is not None:
            if self.api_host not in {"localhost", "127.0.0.1", "::1"}:
                raise ValueError("Development identity requires a loopback API_HOST")
            if any(host not in {"localhost", "127.0.0.1"} for host in self.allowed_hosts):
                raise ValueError("Development identity requires loopback ALLOWED_HOSTS")
            if any(
                urlsplit(origin).hostname not in {"localhost", "127.0.0.1", "::1"}
                for origin in self.allowed_origins
            ):
                raise ValueError("Development identity requires loopback ALLOWED_ORIGINS")
        return self

    @property
    def docs_enabled(self) -> bool:
        return self.api_docs_enabled if self.api_docs_enabled is not None else True
