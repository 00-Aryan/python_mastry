# Python Mastery Backend

This is the local **B1 database and question-storage increment**, building on the tested B0 API. It runs locally on Linux or WSL with Python 3.12 and uv. It includes validated settings, an app factory, structured request logs, safe JSON errors, CORS and host checks, bounded request bodies, health endpoints and generated API documentation.

Question storage and the documented CLI-seeded local development identity are implemented. Deployed authentication, countdowns, code evaluation and learning evidence belong to later increments. No endpoint simulates those features. Production startup is deliberately rejected until deployed authentication is implemented.

## Quick start in WSL and VS Code

Install uv using its official instructions: https://docs.astral.sh/uv/getting-started/installation/

Extract this project under your Linux filesystem, for example `~/projects/python-mastery-backend`, and open it through VS Code's WSL integration. Use its Linux terminal:

```bash
cd ~/projects/python-mastery-backend
uv python install 3.12
uv sync --locked
cp .env.example .env
# Configure PostgreSQL and replace DATABASE_URL credentials first.
uv run alembic upgrade head
uv run mastery-backend
```

Open http://localhost:8000/docs or http://localhost:8000/health/live. The launcher reads API_HOST and API_PORT. Do not share a Windows virtual environment with WSL; select this project's `.venv/bin/python` in VS Code.

Run PostgreSQL natively in Linux/WSL or in a local container. With Docker installed,
this starts a development instance (replace the password before running):

```bash
docker run --name mastery-postgres -e POSTGRES_USER=mastery -e POSTGRES_PASSWORD=CHANGE_ME -e POSTGRES_DB=mastery_development -p 127.0.0.1:5432:5432 -v mastery-postgres-data:/var/lib/postgresql -d postgres:18
```

Set DATABASE_URL in `.env` to that database. Both `postgresql://` and
`postgresql+psycopg://` use psycopg 3. URL query options are rejected; use DB_*
settings for pool sizes and timeouts. Run migrations from the repository root;
migration files live in the source checkout. Startup never creates tables or
runs migrations. The baseline establishes Alembic history; revision 0002 adds local identity,
normalized question storage, constraints and published-content guards.

For live reload, use the explicit Uvicorn command:

```bash
uv run uvicorn mastery_backend.main:create_app --factory --reload --host 127.0.0.1 --port 8000 --no-access-log
```

The direct Uvicorn command uses its CLI host/port options; it does not read API_HOST/API_PORT itself. Disable Uvicorn access logs so our structured logs remain the request-log authority and query-string values are not echoed into access logs.

## Released endpoints

| Endpoint | Response |
|---|---|
| GET /health/live | status alive; release_stage B1-foundation; database not_checked |
| GET /health/ready | database connected; evaluation not_integrated; safe 503 on DB failure |
| GET /api/v1/config/public | Application version and empty learning capabilities/modes |
| GET /api/v1/questions; /api/v1/questions/{question_id}; /api/v1/question-versions/{version_id} | Available published public content only; cursor pagination on the catalog |
| POST /api/v1/admin/questions | Question identity and first draft; admin role and Idempotency-Key required |
| POST /api/v1/admin/questions/{question_id}/versions | New draft with server-assigned version number |
| GET/PATCH/DELETE /api/v1/admin/question-versions/{version_id} | Admin preview, revision-checked draft edit/delete |
| POST /api/v1/admin/question-versions/{version_id}/publish | Validates completeness; 503 until trusted reference verification exists |
| POST /api/v1/admin/questions/{question_id}/archive | Explicit revision-checked archival; preserves published history |
| GET /docs and /redoc | Development API documentation |
| GET /openapi.json | Actual schema generated from implemented endpoints |

Readiness probes PostgreSQL with SELECT 1. It does not certify migration currency, workers or evaluation. Liveness performs no database I/O. Unsupported planned endpoints return a JSON 404. All responses have X-Request-ID and Cache-Control: no-store.

To connect a frontend on port 5173, set `ALLOWED_ORIGINS=["http://localhost:5173"]` in `.env`. Origins include scheme and port. Use one consistent browser hostname. CORS does not provide authentication. Hostnames in ALLOWED_HOSTS are exact values without ports; wildcard and IPv6 host configuration are not supported in this initial release.

## Run the checks

```bash
uv sync --locked
uv run pytest --cov=mastery_backend --cov-report=term-missing
uv run ruff check .
uv run ruff format --check .
uv run mypy src migrations
uv build
```

Unit/API tests inject configuration and database probes and do not require a PostgreSQL server or real `.env`. They cover boundaries, input redaction, host/preflight checks, chunked-body limits, tracing, settings guards, launcher behavior and public-schema accuracy. CI runs the same quality checks and build. Real PostgreSQL tests cover migrations, transactions, UTC, statement timeout and
actual readiness. Without TEST_DATABASE_URL these checks are explicitly skipped.
CI provides PostgreSQL 18. Create a separate database ending in `_test`; tests
reject the same database name as DATABASE_URL:

```bash
docker exec mastery-postgres createdb -U mastery mastery_test
export TEST_DATABASE_URL='postgresql+psycopg://mastery:CHANGE_ME@localhost:5432/mastery_test'
uv run pytest --cov=mastery_backend --cov-report=term-missing
```

Integration tests create and remove only randomly named schemas in that DB.
TEST_DATABASE_URL is read from the shell, not `.env`. Test credentials need schema
creation rights. Use a disposable test database. Question-storage tests also exercise concurrent edits, publication races,
published parent/child guards, authorization and private-content response boundaries.
Evaluation tests will accompany a future trusted execution implementation.

## File responsibilities

| Path | Purpose |
|---|---|
| src/mastery_backend/settings.py | Validate environment and guard release boundaries |
| src/mastery_backend/main.py | Construct app, middleware order and routers |
| src/mastery_backend/cli.py | Load settings and launch server with configured host/port |
| src/mastery_backend/api/routes.py | Released endpoint contracts and responses |
| src/mastery_backend/api/errors.py | Safe, shared JSON error envelope |
| src/mastery_backend/api/middleware.py | Request tracing, host checks, CORS errors and bounded body parsing |
| src/mastery_backend/infrastructure/observability/logging.py | Structured logs and request-local context |
| src/mastery_backend/infrastructure/database/session.py | PostgreSQL engine, independent sessions and connection probe |
| alembic.ini and migrations/ | Credential-free configuration and reviewed revisions |
| tests/ | Corresponding behavioral and regression tests |
| docs/ | Planning contracts, increment decisions, verification records and generated schemas |
| AGENTS.md | Project-wide contributor and coding-agent instructions |

See [B1 database decisions](docs/decisions/0002_b1_database_foundation.md) and [question storage decisions](docs/decisions/0003_question_storage.md) for file responsibilities, data relationships, request flow, transaction ownership and acceptance tests.

## Local content administration

After migrating, explicitly seed a local identity. This UUID is an example for
local setup; roles are database grants and cannot be supplied through HTTP headers:

```bash
uv run mastery-content seed-identity --user-id 00000000-0000-0000-0000-000000000001 --display-name 'Local developer' --role learner --role content_admin
```

Set `DEVELOPMENT_USER_ID=00000000-0000-0000-0000-000000000001` in ignored `.env`,
then seed your reference metadata (an editable example is included):

```bash
uv run mastery-content seed-references docs/reference_catalog.example.json
uv run mastery-backend
```

Missing identity configuration denies admin requests with 401. Missing database
admin grants return 403. The configured identity requires loopback bind/host/origin
settings and local request peers. This is single-operator local mode; production
and deployed sessions remain disabled. Keep API_HOST at 127.0.0.1.

Create an incomplete draft using the family seeded above:

```bash
curl -X POST http://localhost:8000/api/v1/admin/questions -H 'Content-Type: application/json' -H 'Idempotency-Key: create-return-01' -d '{"code":"PY-RETURN-01","family_id":"00000000-0000-0000-0000-000000000031","draft":{"title":"Return a value","statement":"Return the supplied value."}}'
```

Use the returned version ID for admin preview and PATCH. Edits supply the current
`expected_revision`; supplied arrays replace their collections. DELETE supplies
`?expected_revision=N`. Archive supplies the separate `question_revision` through
an `expected_revision` body and requires Idempotency-Key. All state-changing POSTs
require this key; successful identical replay returns its original result.

Publication requires complete validated assets and a trusted executable reference
verification receipt. Complete drafts currently receive `503 VERIFICATION_UNAVAILABLE`
and stay drafts. Incomplete drafts receive a validation conflict. **There is no
production/test-verifier switch or publication bypass in the CLI.** Public catalog
reads remain empty until verified published content exists. The test-only verifier
validates the publication transition; it does not validate any future verifier.

Read the [question storage decision](docs/decisions/0003_question_storage.md) for
content types, enum/position choices and the exact acceptance checks. The generated
[OpenAPI schema](docs/openapi.b1-question-storage.json) describes released routes.

## Diagnose a failure

Read X-Request-ID from the response, then find the matching structured log. Logs include operation, status_code and duration_ms. Unexpected exceptions retain exception type and stack frame file/line/function, while omitting exception values and source text to reduce secret exposure. Validation errors report field paths and reason codes without rejected inputs.

If startup fails, check the named setting, JSON formatting for list variables and the selected WSL interpreter. The launcher reports only invalid configuration fields. An occupied port requires stopping the existing process or selecting a different API_PORT; it is not a settings validation failure.

A browser CORS error usually means a mismatched origin. Host errors require a matching ALLOWED_HOSTS entry. A 413 means the actual or declared body exceeds MAX_REQUEST_BODY_BYTES. MAX_CODE_BYTES and MAX_PAGE_SIZE are validated future boundary settings; no code-save or paginated endpoints exist to apply them yet.

## Next increment

Question storage is implemented. Production publication remains unavailable until a trusted reference verifier is implemented; the test-only injected verifier proves transition logic, not the correctness of a future verifier. Later increments add the skill DAG, attempts/timers, isolated execution and learning evidence. Do not enable hosted use by removing the B0 startup guard without implementing its requirements.
