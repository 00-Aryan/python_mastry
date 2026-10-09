# B1 database foundation verification

Verified on 9 October 2026 in Linux, Python 3.12.14 and uv 0.12.23.
The locked additions are SQLAlchemy 2.1.4, psycopg/psycopg-binary 3.3.6 and
Alembic 1.20.0. Dependency resolution and installation completed through uv.

- Before implementation: all 49 B0 tests, Ruff lint/format, strict mypy and
  source/wheel builds passed.
- After implementation: `uv sync --locked` completed; all 67 pytest cases passed
  with 99% statement coverage. No integration checks were skipped in this run.
- Real PostgreSQL 18.6 ran temporarily on localhost port 55432, with a separate
  `mastery_test` database. Tests verified migration upgrade/replay/downgrade/
  re-upgrade, Alembic revision uniqueness, transaction commit/rollback, UTC,
  enforced statement timeout, cancellation recovery and actual API readiness.
- The test-database guard rejects ordinary DB names and matching application DB
  names, including configuration loaded from `.env`.
- `uv run alembic upgrade head` also passed through the normal settings-based
  CLI connection path against that temporary database.
- Ruff lint and formatting checks passed; strict `mypy src migrations` passed
  for 15 source files.
- `uv build` produced a source distribution and wheel. The source archive was
  inspected for Alembic configuration, revisions, lockfile and Python version.
  Migration operations require the checkout or unpacked source archive; the
  wheel contains the application package.
- `docs/openapi.b1-foundation.json` was generated from the implemented app.

The sandboxed B0 TestClient run stalled; tests were rerun successfully outside
that sandbox. Restricted network access also prevented isolated build dependency
resolution; the authorized network-enabled builds passed. A writable temporary
uv cache was used because the normal cache directory was read-only.

CI now supplies PostgreSQL 18 but no remote CI run was performed. The Docker/WSL
setup instructions were not executed here; local verification used temporary
PostgreSQL binaries extracted under `/tmp`, without installing a system service.
No deployed authentication, application content tables, locking use cases,
timers, runner or learning evidence was implemented or claimed as verified.

This workspace has no `.git` repository, so a Git diff or commit was unavailable.
Changed source, tests, migration files, setup notes and packaging configuration
were reviewed directly.
