"""Local launcher honors validated host and port settings."""

import uvicorn
from pydantic import ValidationError

from mastery_backend.main import create_app
from mastery_backend.settings import Settings


def main() -> None:
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
    uvicorn.run(
        create_app(settings), host=settings.api_host, port=settings.api_port, access_log=False
    )
