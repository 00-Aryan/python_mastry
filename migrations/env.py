"""Read the same secret settings as the API; never embed a URL in Alembic config."""

from alembic import context
from pydantic import ValidationError
from sqlalchemy import Connection

from mastery_backend.infrastructure.database import (
    assistance_models,  # noqa: F401
    attempt_models,  # noqa: F401
    submission_models,  # noqa: F401
)
from mastery_backend.infrastructure.database.content_models import Base
from mastery_backend.infrastructure.database.session import create_database_engine
from mastery_backend.settings import Settings


def run_migrations() -> None:
    supplied_connection = context.config.attributes.get("connection")
    if isinstance(supplied_connection, Connection):
        context.configure(
            connection=supplied_connection, transactional_ddl=True, target_metadata=Base.metadata
        )
        with context.begin_transaction():
            context.run_migrations()
        return
    try:
        settings = Settings()
    except ValidationError:
        raise SystemExit("Invalid database migration configuration; check settings.") from None

    engine = create_database_engine(settings)
    try:
        if context.is_offline_mode():
            context.configure(
                dialect_name="postgresql",
                literal_binds=True,
                transactional_ddl=True,
                target_metadata=Base.metadata,
            )
            with context.begin_transaction():
                context.run_migrations()
        else:
            with engine.connect() as connection:
                context.configure(
                    connection=connection, transactional_ddl=True, target_metadata=Base.metadata
                )
                with context.begin_transaction():
                    context.run_migrations()
    finally:
        engine.dispose()


run_migrations()
