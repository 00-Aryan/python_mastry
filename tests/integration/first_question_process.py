"""Test-only process entrypoint: real CLI/API with disposable-schema configuration.

Only settings and database search_path are wired here. Authentication, clocks,
publication, runner admission, execution and result application use production code.
Nothing in the installed package imports this driver or supplies a fake adapter.
"""

import json
import sys
from pathlib import Path
from uuid import UUID

import uvicorn
from sqlalchemy import event
from sqlalchemy.engine import make_url

from mastery_backend.infrastructure.database.session import create_database_engine
from mastery_backend.settings import Settings


def main():
    config = json.loads(Path(sys.argv[1]).read_text())
    url = make_url(config["database_url"])
    schema = config["schema"]
    assert url.database.endswith("_test") and url.host in {"localhost", "127.0.0.1"}
    assert schema.startswith("integration_") and schema.replace("_", "").isalnum()
    settings = Settings(
        _env_file=None,
        app_env="development",
        database_url=config["database_url"],
        development_user_id=UUID(config["user_id"]),
        local_runner_enabled=True,
        publication_evaluator_policy_version_id=config.get("approved_policy_id"),
        api_port=config.get("port", 8000),
        log_level="WARNING",
    )

    def scoped_engine(configuration):
        engine = create_database_engine(configuration)

        @event.listens_for(engine, "connect")
        def set_schema(connection, record):
            with connection.cursor() as cursor:
                cursor.execute('SET search_path TO "' + schema + '"')
            connection.commit()

        return engine

    if config["component"] == "api":
        from mastery_backend import main as api

        api.create_database_engine = scoped_engine
        uvicorn.run(
            api.create_app(settings),
            host="127.0.0.1",
            port=settings.api_port,
            access_log=False,
            log_level="warning",
        )
    else:
        from mastery_backend import content_cli, worker_cli

        cli = content_cli if config["component"] == "content" else worker_cli
        assert config["component"] in {"content", "worker"}
        cli.create_database_engine = scoped_engine
        cli.Settings = lambda: settings
        sys.argv = ["s015-test-process", *config["arguments"]]
        cli.main()


if __name__ == "__main__":
    main()
