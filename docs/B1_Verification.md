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

## Question storage increment — 9 October 2026

The earlier database-foundation results above are historical. Git was initialized
with reviewed ignore rules, the configured author identity was used without
inventing one, and the reverified 67-test foundation was committed as `766756a`.

Final verification for question storage used the same Python 3.12.14/uv 0.12.23
Linux environment and real PostgreSQL 18.6 on the temporary localhost server.
No runtime dependency was added; uv.lock remains consistent with pyproject.toml.

- `uv sync --locked`: passed.
- `uv run pytest --cov=mastery_backend --cov-report=term-missing` with a separate
  TEST_DATABASE_URL: **115 passed**, **97% statement coverage**, no skips or
  warnings. This includes the existing regression suite and the new storage
  tests. Test sessions/connections use isolated, randomly named schemas.
- `uv run ruff check .` and `uv run ruff format --check .`: passed.
- Strict `uv run mypy src migrations`: passed for **37 source files**.
- Normal settings-based `uv run alembic upgrade head`: passed against the
  temporary PostgreSQL database. `alembic current` reported
  `0002_question_storage (head)`; `alembic check` reported no new upgrade operations.
- Real PostgreSQL tests upgraded from `0001_database_baseline`, replayed head,
  compared schema with ORM metadata, downgraded/re-upgraded the disposable schema,
  and checked FK/unique/check constraints and the partial primary-skill index.
- `uv build`: source distribution and wheel passed. Archive inspection confirmed
  reviewed migrations/configuration, lockfile, Python version and application
  modules were present, the wheel includes the mastery-content entry point, and
  neither `.env`/virtual environments nor test modules were included in the wheel.
- `docs/openapi.b1-question-storage.json` was generated from the real app. It has
  11 resource paths, distinct operation IDs, explicit public/admin models and the
  documented publication 503 error contract.

### Explicit acceptance results

| Requirement | Actual verification |
|---|---|
| Published parent and all owned content are immutable | Direct PostgreSQL UPDATE/DELETE/INSERT attempts were rejected for version-owned tests, assistance, solution, skills, patterns, modes, examples and links; parent edits/deletion/unpublication were rejected. SQLSTATE 23514 was checked. |
| Concurrent edits | Two concurrent HTTP PATCH requests at revision 1 produced exactly one 200 and one `409 STALE_REVISION`; stored revision became 2. |
| Snapshot verified outside transactions | The blocking test verifier received immutable JSON bytes and observed zero checked-out pooled connections. A concurrent revision edit, private-test hash change or archival committed while verification was paused; publication was rejected after rechecking locks/state/hash. |
| Verifier unavailable | The actual default dependency returned `503 VERIFICATION_UNAVAILABLE` with the request ID; draft content, revision, published_at and receipt stayed unchanged, with no successful publication idempotency record. |
| Authorization | Stored-role revocation denied writes/admin reads/replay and a stale service principal. Disabled/missing/configuration-less identity denied access. Spoofed role/user headers did not grant access; production/public-bind/origin settings and unsafe origins were rejected. |
| Private content boundaries | Sentinels in private tests, assistance, solution and rubrics were absent from question detail, version detail, lists and errors. Catalog SQL avoided private asset tables and used six queries for a multi-question page. Unexpected verifier faults and database faults returned safe 500/503 responses. |
| Transaction recovery | A failure after flushing replacement children rolled back the entire draft, including private assets. Invalid references, uniqueness conflicts and failed seed FKs left no partial records or false idempotent success. Concurrent identical POSTs produced one stored question and one durable replay result. |
| Storage lifecycle | Revision-checked CRUD, replacement collections, non-reused version numbers, explicit archival, highest-published-version selection, old-version retrieval, filters/cursors and local CLI setup passed. |

Initial expanded tests exposed missing test imports; these were corrected before
the successful final run. Restricted network access prevented a local editable
package rebuild until the authorized network-enabled uv invocation completed.
Tests requiring TestClient threads and local PostgreSQL ran outside the restrictive
sandbox. No failed or stalled run is counted as passed.

The source and staged diff were reviewed before the increment commit. Ignore rules
cover environment files, credential paths/key files, environments/caches/build
output and local database artifacts. Git author identity was already configured;
no identity was created or changed.

### Limits and unresolved work

**Question storage is implemented; production publication remains unavailable
until a trusted reference verifier is implemented.** The successful injected
verifier is defined only in tests. It validates the transition logic, not executable
correctness or the behavior/security of a future verifier. There is no runtime
verification-success override. Production startup/deployed authentication remain
blocked as documented.

Concrete content enums, JSON argument format, position rules, DELETE revisions,
archive revision and local setup are recorded in
[the question-storage decision](decisions/0003_question_storage.md), resolving the
planning contracts' unspecified details without implementing a DAG or evaluator.
Full content import tooling, deployed login/CSRF, trusted execution, backup/restore
and hosted use are subsequent work. No DAG traversal, timer, submission, execution
or Bayesian behavior was added. No remote CI run or Docker/WSL setup run was
performed; those environments remain unverified.
