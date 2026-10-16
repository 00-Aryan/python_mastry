"""Explicit local authoring commands; execution stays in separately isolated processes."""

import argparse
from pathlib import Path
from typing import Literal, cast
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from mastery_backend.application.content_seed_service import (
    seed_development_identity,
    seed_reference_catalog,
)
from mastery_backend.domain.content import ContentError
from mastery_backend.domain.content_seed import ReferenceCatalogSeed
from mastery_backend.infrastructure.database.session import (
    create_database_engine,
    create_session_factory,
)
from mastery_backend.infrastructure.observability.logging import configure_logging, logger
from mastery_backend.settings import Settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Local identity and authoring reference setup")
    subparsers = parser.add_subparsers(dest="command", required=True)
    identity = subparsers.add_parser("seed-identity")
    identity.add_argument("--user-id", type=UUID, required=True)
    identity.add_argument("--display-name", required=True)
    identity.add_argument(
        "--role", action="append", choices=["learner", "content_admin"], required=True
    )
    references = subparsers.add_parser("seed-references")
    references.add_argument("file", type=Path)
    verify = subparsers.add_parser("verify-reference")
    verify.add_argument("--version-id", type=UUID, required=True)
    verify.add_argument("--expected-revision", type=int, required=True)
    verify.add_argument("--runtime", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        settings = Settings()
    except ValidationError as error:
        fields = sorted(
            {
                ".".join(str(part) for part in issue["loc"]) or "configuration"
                for issue in error.errors()
            }
        )
        raise SystemExit("Invalid configuration fields: " + ", ".join(fields)) from None
    configure_logging(settings.log_level)
    engine = create_database_engine(settings)
    try:
        factory = create_session_factory(engine)
        if arguments.command == "seed-identity":
            roles = cast(set[Literal["learner", "content_admin"]], set(arguments.role))
            seed_development_identity(factory, arguments.user_id, arguments.display_name, roles)
            print(f"Seeded local identity {arguments.user_id}; configure DEVELOPMENT_USER_ID.")
        elif arguments.command == "verify-reference":
            from mastery_backend.application.clock import SystemClock
            from mastery_backend.application.identity_service import read_development_principal
            from mastery_backend.application.publication_artifact_service import (
                PublicationArtifactService,
            )
            from mastery_backend.infrastructure.runner.local_sandbox import LocalSandbox

            if settings.app_env != "development":
                raise ContentError(
                    "VERIFICATION_UNAVAILABLE", "Local verification requires development."
                )
            principal = read_development_principal(factory, settings.development_user_id)
            try:
                sandbox = LocalSandbox(arguments.runtime)
            except (OSError, RuntimeError, ValueError):
                raise ContentError(
                    "VERIFICATION_UNAVAILABLE", "Trusted isolation is unavailable."
                ) from None
            report = PublicationArtifactService(factory, SystemClock(), sandbox).verify(
                principal, arguments.version_id, arguments.expected_revision
            )
            print(report.model_dump_json())
            if report.result.outcome != "passed":
                raise SystemExit(1)
        else:
            try:
                catalog = ReferenceCatalogSeed.model_validate_json(arguments.file.read_bytes())
            except (OSError, ValidationError):
                raise SystemExit(
                    "Reference file is unreadable or invalid; no records changed."
                ) from None
            seed_reference_catalog(factory, settings.development_user_id, catalog)
            print("Authoring references seeded.")
    except ContentError as error:
        raise SystemExit(f"{error.code}: {error.message}") from None
    except SQLAlchemyError:
        logger.exception("content_setup_database_failed")
        raise SystemExit("Database setup failed; check connection and migrations.") from None
    finally:
        engine.dispose()
