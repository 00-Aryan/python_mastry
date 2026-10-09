# Python Mastery Backend

This is the local **B1 database foundation**, building on the tested B0 API. It runs locally on Linux or WSL with Python 3.12 and uv. It includes validated settings, an app factory, structured request logs, safe JSON errors, CORS and host checks, bounded request bodies, health endpoints and generated API documentation.

Questions, authentication, countdowns, code evaluation and learning evidence belong to later increments. No endpoint simulates those features. Production startup is deliberately rejected until deployed authentication is implemented.

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
runs migrations. The first revision establishes Alembic history only; identity
and content tables are future B1 increments.

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
uv run mypy src
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
creation rights. Use a disposable test database. Concurrency, application
constraints and evaluation tests follow with their implemented use cases.

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

Database infrastructure is implemented; application services, ORM entities and learning rules follow with their use cases. See [B1 database decisions](docs/decisions/0002_b1_database_foundation.md) for request flow, transaction ownership and acceptance tests.

## Diagnose a failure

Read X-Request-ID from the response, then find the matching structured log. Logs include operation, status_code and duration_ms. Unexpected exceptions retain exception type and stack frame file/line/function, while omitting exception values and source text to reduce secret exposure. Validation errors report field paths and reason codes without rejected inputs.

If startup fails, check the named setting, JSON formatting for list variables and the selected WSL interpreter. The launcher reports only invalid configuration fields. An occupied port requires stopping the existing process or selecting a different API_PORT; it is not a settings validation failure.

A browser CORS error usually means a mismatched origin. Host errors require a matching ALLOWED_HOSTS entry. A 413 means the actual or declared body exceeds MAX_REQUEST_BODY_BYTES. MAX_CODE_BYTES and MAX_PAGE_SIZE are validated future boundary settings; no code-save or paginated endpoints exist to apply them yet.

## Next increment

The next B1 increment adds identities/roles, question drafts, publication and their constraints and storage tests. Later increments add the skill DAG, attempts/timers, isolated execution and learning evidence. Do not enable hosted use by removing the B0 startup guard without implementing its requirements.
