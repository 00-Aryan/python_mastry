"""Native Task Scheduler entry point; does not alter PowerShell execution policy."""

from mastery_backend.automation.windows_scheduler import main

if __name__ == "__main__":
    main()
