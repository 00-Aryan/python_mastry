"""Repository entry point; use uv run --locked scripts/automation/run_sprint.py."""

from mastery_backend.automation.controller import main

if __name__ == "__main__":
    main()
