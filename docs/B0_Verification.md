# B0 verification record

Verified on 9 October 2026 in Linux using Python 3.12.14 and uv 0.12.23.

- uv sync --locked completed successfully.
- Ruff lint and format checks passed.
- mypy strict checks passed for 11 source files.
- 49 pytest cases passed, with 99% statement coverage, including malformed headers, preflight host validation and safe browser-visible internal errors.
- uv build produced a source distribution and wheel.
- The installed mastery-backend launcher served an actual HTTP liveness response and an OpenAPI schema containing exactly three released resource paths.
- docs/openapi.b0.json was generated from the implemented application.

CI configuration is included, but no remote GitHub Actions run was performed. WSL instructions are provided; this session's execution environment was Linux, not the user's laptop. PostgreSQL integration, deployed authentication and learner-code execution were not implemented or tested in B0.

The regression suite does not prove the absence of all defects. Future issues should be reproduced with a request ID and a focused failing test before a fix.
