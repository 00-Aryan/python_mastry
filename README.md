# Python Mastery Backend

This is the local **B6a evaluation-lifecycle increment**, building on the tested B0 API. It runs locally on Linux or WSL with Python 3.12 and uv. It includes validated settings, an app factory, structured request logs, safe JSON errors, CORS and host checks, bounded request bodies, health endpoints and generated API documentation.

Question storage, skill CRUD/prerequisite DAG storage, owned attempts/server timers, progressive assistance, immutable source receipts, evaluation orchestration and the documented CLI-seeded local development identity are implemented. Deployed authentication, code evaluation and learning evidence belong to later increments. No endpoint simulates those features. Production startup is deliberately rejected until deployed authentication is implemented.

S012 adds a separate local `mastery-content verify-reference` command and immutable
reference-verification artifacts. See [its setup, limits and publication boundary](docs/decisions/0010_publication_artifacts.md).
Publication remains unavailable until S013; a passing artifact does not certify test quality.

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
normalized question storage, constraints and published-content guards. Revision 0003 adds skill revisions and prerequisite edges while retaining existing skills and mappings. Revision 0004 adds pinned timer policy, attempts, phases and event history. Revision 0005 adds immutable assistance grants and waiting phases without changing existing attempt pins. Revision 0006 adds immutable submissions and acceptance events.

For live reload, use the explicit Uvicorn command:

```bash
uv run uvicorn mastery_backend.main:create_app --factory --reload --host 127.0.0.1 --port 8000 --no-access-log
```

The direct Uvicorn command uses its CLI host/port options; it does not read API_HOST/API_PORT itself. Disable Uvicorn access logs so our structured logs remain the request-log authority and query-string values are not echoed into access logs.

## Released endpoints

| Endpoint | Response |
|---|---|
| GET /health/live | status alive; release_stage B5-immutable-submissions; database not_checked |
| GET /health/ready | database connected; evaluation not_integrated; safe 503 on DB failure |
| GET /api/v1/config/public | Application version; attempt_lifecycle/server_timers/progressive_assistance/submission_receipts capabilities; practice/assessment modes |
| GET /api/v1/questions; /api/v1/questions/{question_id}; /api/v1/question-versions/{version_id} | Available published public content only; cursor pagination on the catalog |
| POST /api/v1/admin/questions | Question identity and first draft; admin role and Idempotency-Key required |
| POST /api/v1/admin/questions/{question_id}/versions | New draft with server-assigned version number |
| GET/PATCH/DELETE /api/v1/admin/question-versions/{version_id} | Admin preview, revision-checked draft edit/delete |
| POST /api/v1/admin/question-versions/{version_id}/publish | Validates completeness; 503 until trusted reference verification exists |
| POST /api/v1/admin/questions/{question_id}/archive | Explicit revision-checked archival; preserves published history |
| GET /api/v1/skills; /api/v1/skills/{skill_id}; /api/v1/skills/graph | Bounded skill catalogs and graph/neighborhood snapshots |
| POST /api/v1/admin/skills; PATCH /api/v1/admin/skills/{skill_id} | Admin skill creation and revision-checked metadata edits |
| POST /api/v1/admin/skills/{skill_id}/archive | Validated archival preserving history |
| POST/PUT /api/v1/admin/skills/{dependent_id}/prerequisites; DELETE /api/v1/admin/skills/{dependent_id}/prerequisites/{prerequisite_id} | Serialized, revision-checked DAG edge changes |
| POST/GET /api/v1/attempts; GET /api/v1/attempts/{attempt_id} | Start and read owned attempts with server timing snapshots |
| GET /api/v1/attempts/{attempt_id}/question | Exact pinned public version, including owned historical archived content |
| POST /api/v1/attempts/{attempt_id}/pause, /resume, /extend, /defer, /abandon | Revision-checked, idempotent lifecycle/timer commands |
| POST /api/v1/attempts/{attempt_id}/assistance/next, /solution; GET /api/v1/attempts/{attempt_id}/assistance | Owned staged grants, confirmed full-solution escape and grant history |
| POST/GET /api/v1/attempts/{attempt_id}/submissions; GET /api/v1/submissions/{submission_id} | Owned immutable source receipt, bounded metadata history and detail; no execution |
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
[OpenAPI schema](docs/openapi.b5-immutable-submissions.json) describes released routes.

## Diagnose a failure

Read X-Request-ID from the response, then find the matching structured log. Logs include operation, status_code and duration_ms. Unexpected exceptions retain exception type and stack frame file/line/function, while omitting exception values and source text to reduce secret exposure. Validation errors report field paths and reason codes without rejected inputs.

If startup fails, check the named setting, JSON formatting for list variables and the selected WSL interpreter. The launcher reports only invalid configuration fields. An occupied port requires stopping the existing process or selecting a different API_PORT; it is not a settings validation failure.

A browser CORS error usually means a mismatched origin. Host errors require a matching ALLOWED_HOSTS entry. A 413 means the actual or declared body exceeds MAX_REQUEST_BODY_BYTES. MAX_PAGE_SIZE also caps catalog pages. MAX_CODE_BYTES limits UTF-8 submission source; larger source returns 413.

## Next increment

Question storage is implemented. Production publication remains unavailable until a trusted reference verifier is implemented; the test-only injected verifier proves transition logic, not the correctness of a future verifier. Skill CRUD and the prerequisite DAG are implemented. Attempt lifecycle and server timers are implemented. Progressive assistance is implemented. Immutable source receipts are implemented. Later increments add code drafting, recommendations, isolated execution and learning evidence. Do not enable hosted use by removing the B0 startup guard without implementing its requirements.

## Skill graph administration

Use the same seeded content_admin identity. Create a skill with curriculum_id,
code, title and competency. PATCH accepts title/competency plus expected_revision;
identity fields remain stable. GET /api/v1/skills/graph?curriculum_id=UUID returns
nodes, prerequisite -> dependent edges and graph_revision. Supply that revision
when adding, removing or replacing prerequisites. PUT replaces all prerequisites
of one dependent and validates the resulting DAG atomically. POST commands require
Idempotency-Key; DELETE returns 204 and the graph must be reloaded.

All graph mutations lock their curriculum in PostgreSQL. Archive requires removing
incident edges and resolving mappings on available questions first. Historical
mappings on archived questions remain intact. Archived skill detail remains
readable, while default catalogs and active graphs omit it. Prerequisites are
recommendation guidance and do not restrict access to published questions.

Graph reads support center_skill_id, direction and depth (1–5), with max_nodes
up to 100 and max_edges up to 500. Oversized results return GRAPH_READ_LIMIT;
select a smaller neighborhood. Catalog pages use filter-bound cursors, up to 100
items. Read [the skill graph decision](docs/decisions/0004_skill_graph.md) for
request flow, relationships, archival/revision choices and acceptance tests, and
[the verification record](docs/B2_Verification.md) for actual checks and limits.

## Attempt lifecycle and timers

Use a seeded identity with the database learner role. Production publication still
requires a trusted verifier, so local attempt starts need already verified published
content; no seed or CLI command bypasses publication. Tests supply controlled
published fixtures with a test-only verifier.

POST /api/v1/attempts takes question_version_id, mode (practice/assessment) and
independent_budget_seconds (60–3600), plus Idempotency-Key. Ownership comes from the
configured database identity. The response returns the immutable question/policy
pins, revision, lifecycle and a timer with server_now/remaining_ms. Animate the
countdown locally with a frontend monotonic clock; reload/reconnect via GET. Never
send elapsed time or a desired result/status.

Pause/resume/extend/defer/abandon supply expected_revision and Idempotency-Key.
Pause excludes time only after the server accepts it; closing/offlining a browser
keeps the active timer running. Extension is limited to 1–1800 seconds per command,
with 3600 total, and is rejected at/after expiry. Defer ends unresolved; abandon
stops voluntarily. Neither marks an answer wrong or successful. Assessment pauses
and extensions permanently record timing accommodation.

At expiry, the independent phase ends and assistance becomes eligible. No hint is
delivered and the learning session stays active. Total active/overdue solving time
continues until pause/end. Reads project timestamps rather than writing every tick;
first-observed expiry is recorded once. Expiry/closure cannot be erased to regain
an independent interval. Retry with the same key/payload for its original result;
GET afterward for current server time. Invalid/stale transitions return 409.

An existing owned attempt keeps its pinned public question after archival through
GET /api/v1/attempts/{id}/question. Archived questions cannot start new attempts;
private tests, hints and solutions remain excluded. Public attempt lists are bounded
and owner-only. Read [the timer/state decision](docs/decisions/0005_attempt_timers.md)
and [B3 verification](docs/B3_Verification.md) for rules, responsibilities, actual
checks and unresolved limits. B4 adds the assistance commands below; code execution and learning
calculations remain unreleased.


## Progressive assistance

Use POST /api/v1/attempts/{id}/assistance/next with expected_revision,
trigger=learner_request or budget_expired and Idempotency-Key. The first hint may
be requested early; later hints wait for the current active-time interval to
expire. Pause stops that interval, resume restarts it, and extensions preserve
irreversible grants. Responses expose only that stage, with its grant timestamp,
reason and current attempt snapshot. GET /attempts/{id}/assistance recovers granted
content only. Generic public and attempt detail/list/question responses stay private.

Confirm the full-solution escape using /assistance/solution with
expected_revision and confirmation=true. It is immediately available on active/
paused attempts and does not mark an answer correct or end the session. Ordinary
next never exposes the final solution without this confirmation. Defer/abandon
prohibit new grants. Identical key/body retries recover the original response
indefinitely, including after a lost response or terminal transition; GET attempt
again for current timing. Distinct competing commands use revision conflicts.

New attempts pin pilot-assistance-1. B3 attempts retain pilot-timer-1 and return
503 POLICY_UNAVAILABLE for new help; no existing policy is retroactively changed.
Missing assets return safe 503 and leave the grant transaction unchanged. Read
[assistance rules](docs/decisions/0006_progressive_assistance.md) and
[B4 verification](docs/B4_Verification.md) for relationships, request flow,
acceptance results and unverified limits. Production publication remains unavailable
until a trusted verifier exists; test-only verifier fixtures do not enable it.


## Immutable source submissions

POST /api/v1/attempts/{id}/submissions takes source_code, purpose=public_run or
assessment, expected_revision and Idempotency-Key. Only active/paused owners can
submit. Responses say received/not_requested: source has been stored, never parsed,
executed or graded. Invalid Python syntax is accepted unchanged. Nonblank valid
UTF-8 text without NUL is required; MAX_CODE_BYTES defaults to 65536 encoded bytes,
while the whole JSON request must fit MAX_REQUEST_BODY_BYTES (262144 by default).

Each receipt pins question/policy versions and preserves its acceptance-time timer,
assistance grants, accommodation and family context. Later assistance cannot change
it. Concurrent submission/help/timer commands share attempt locks and revisions.
Identical retries return the same immutable receipt indefinitely; changed payload
at the same key returns 409. Distinct keys create distinct submissions, including
repeated source. No receipt starts a pending assessment job or blocks help.

GET /api/v1/submissions/{id} returns owned source/detail. GET
/api/v1/attempts/{id}/submissions returns bounded metadata pages without source or
full evidence. Reads never alter receipt clocks. No response loads hidden tests,
hints or solutions; logs omit learner source. See [submission rules](docs/decisions/0007_immutable_submissions.md)
and [B5 verification](docs/B5_Verification.md) for ordering, constraints and actual
checks. Execution, grading, recommendations and mastery remain future increments.

## Evaluation lifecycle and runner interface

B6a adds POST /api/v1/submissions/{id}/evaluations with expected_revision and
Idempotency-Key, GET /api/v1/evaluations/{id}, and bounded
GET /api/v1/attempts/{id}/evaluations. Default admission returns 503
EVALUATION_UNAVAILABLE unless a supported isolated worker is enabled and ready. RUNNER_URL cannot enable
execution; test adapters are defined only in tests and rejected outside APP_ENV=test.
The API never interprets or executes learner source.

When a supported adapter is introduced, admission atomically pins an immutable
submission, published test bundle and evaluator policy, records a pending job and
durable dispatch intent, and advances the attempt revision. Leased dispatch happens
outside transactions; stale/duplicate results cannot overwrite a terminal result.
Infrastructure failures have a separate category from incorrect/syntactically invalid
code. Status/history reveal no hidden assets, source or raw diagnostics.

Pending assessment jobs block new assistance/assessment commands. Timers continue,
and pause/end remain available. Bounded retries and a five-minute deadline prevent
an indefinite help lock: valid help admission also finalizes overdue jobs if the
worker stopped. Immutable receipt evidence and exact successful retries remain intact.
Results do not end attempts, award eligibility or change mastery.

Read [evaluation rules](docs/decisions/0008_evaluation_lifecycle.md) for state/protocol,
identity and isolation release gates, and [B6a verification](docs/B6a_Verification.md)
for actual tests and unverified guarantees. Publication verification, recommendations and mastery remain outside this increment.


## B6b local isolated worker

A separate `mastery-worker` process executes Python using Bubblewrap, systemd cgroup
limits and an explicit seccomp profile. It grades bounded JSON outside the sandbox,
authenticates with an operator-provisioned credential and records signed immutable
provenance. The API holds only a short-lived worker admission descriptor. Default
`LOCAL_RUNNER_ENABLED=false` denies new evaluations with 503; missing capabilities,
credentials or readiness keep them unavailable. Health readiness reports evaluation
availability separately from API/database readiness.

Follow [local WSL setup](docs/Local_Runner_Setup.md), [trust boundary and controls](docs/decisions/0009_local_isolated_runner.md)
and [B6b verification](docs/B6b_Verification.md). No host project directories/private
assets/credentials enter isolation. Real verification includes adversarial submissions
and a real killed supervisor, with independent systemd timeout cleanup. This is a
local shared-kernel boundary, not a deployment or production certification.
Publication remains unavailable until its separate trusted verifier is implemented.


## Roadmap workflow

Read [the current status](docs/roadmap/STATUS.md) and [master roadmap](docs/roadmap/Master_Roadmap.md)
before choosing work. Sprint records under `docs/roadmap/sprints/` link actual commits,
verification and blockers. The inventory distinguishes implemented B6b code from its
still-open real-isolation verification gate; historical descriptions above are not
proof of current release readiness.

Unattended sprint operation: [setup and exact controls](docs/automation/Sprint_Automation.md).
