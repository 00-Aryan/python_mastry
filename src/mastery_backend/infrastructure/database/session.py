"""Bounded synchronous connections; use cases own session transactions."""

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from mastery_backend.settings import Settings


def create_database_engine(settings: Settings) -> Engine:
    # Both accepted URL spellings select psycopg 3, never the psycopg2 default.
    url = make_url(settings.database_url.get_secret_value()).set(drivername="postgresql+psycopg")
    return create_engine(
        url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout_seconds,
        pool_pre_ping=True,
        hide_parameters=True,
        connect_args={
            "connect_timeout": settings.db_connect_timeout_seconds,
            "options": f"-c timezone=UTC -c statement_timeout={settings.db_statement_timeout_ms}",
        },
    )


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Each call creates an independent session; closing rolls back uncommitted work."""
    return sessionmaker(bind=engine, expire_on_commit=False)


def check_database_connection(engine: Engine) -> None:
    """Read-only probe; exceptions are translated only at the API boundary."""
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
