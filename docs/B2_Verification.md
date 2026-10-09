# Skill graph increment verification

Verified: 9 October 2026, Linux, Python 3.12.14, uv 0.12.23 and real PostgreSQL 18.6.
Decision: [skill graph storage](decisions/0004_skill_graph.md).
API: [released contract](REST_API_Settings_and_Contract.md#released-skill-graph-increment-9-october-2026)
and [generated OpenAPI](openapi.b2-skill-graph.json).

## Baseline and actual checks

Before implementation the clean question-storage baseline passed **115 tests**
with PostgreSQL, `uv sync --locked`, Ruff and strict mypy (37 source files).
Existing skill identities, curriculum relationships and version mappings were
inspected and reused. No runtime dependency or independent dependency list was
added; pyproject.toml, uv.lock and .python-version remain consistent.

Final checks on this increment:

| Check | Actual result |
|---|---|
| `uv sync --locked` | Passed |
| `TEST_DATABASE_URL=… uv run pytest --cov=mastery_backend --cov-report=term-missing -W error` | **137 passed**, **98% statement coverage**, no skips or warnings |
| `uv run ruff check .` | Passed |
| `uv run ruff format --check .` | Passed, 69 files |
| `uv run mypy src migrations` | Strict checking passed, 46 source files |
| `DATABASE_URL=… uv run alembic upgrade 0002_question_storage`, then `upgrade head` | Passed against actual disposable PostgreSQL |
| `uv run alembic current` | `0003_skill_graph (head)` |
| `uv run alembic check` | No new upgrade operations detected |
| `uv build` | Source distribution and wheel built successfully |
| Package archive inspection | Migration/config/lock/Python version/decision/OpenAPI present in source; graph application/domain/repository modules and CLI entry points present in wheel; no environment, virtual environments or runtime test verifier |
| Installed wheel smoke check | Passed from a temporary wheel target; imported the packaged module and generated 19-path OpenAPI using project dependency environment |
| OpenAPI generation from app factory | Passed; 19 paths; DELETE edge documents 204; distinct operation IDs checked in regression suite |
| `git diff --check` and source review | Passed; reviewed transaction order, revision refresh, archive/mapping rules, constraints, public allowlists and stage boundaries |

Tests use independent sessions/connections in randomly named schemas of a separate
`mastery_test` database. Startup still never runs migrations. The normal migration
CLI was checked separately from fixture-based migrations.

## Explicit acceptance evidence

| Requirement | Actual verification |
|---|---|
| Chains, branching and shared prerequisites | Chain/branch/diamond/disconnected graph tests passed; a 2,500-node chain and its cycle exercised iterative validation without recursion limits |
| Direct/indirect cycles and actionable errors | API and domain self/direct/longer-cycle checks passed; cycle errors contain involved skill codes |
| Edge uniqueness and foreign keys | PostgreSQL rejected self-links (23514), missing/cross-curriculum endpoints (23503) and duplicate edges (23505); services returned documented safe conflicts/input errors |
| Serialized graph transactions | Two different admins reached the curriculum lock concurrently before opposing additions: exactly one committed, one received STALE_REVISION; inverse retry at the new revision received GRAPH_CYCLE; one edge and one revision increment remained |
| Concurrent skill edits | Two different admins preloaded the same revision and raced at the curriculum lock: exactly one edit committed and one received STALE_REVISION; locked ORM refresh preserved revision 2 |
| Rollback | Cycle-rejected incoming-set replacement retained all old edges/revision; injected failure after replacement flush rolled back both; failed create/FK/uniqueness commands left no false idempotency result |
| Admin authorization | Database-role revocation denied create/edit/archive/add/replace/delete and POST replay despite spoofed headers; stale service principal was rechecked; missing identity configuration returned 401 |
| Archival | Incident edges block archive until explicitly removed; available question mappings block archive; archived skills cannot be edited/linked and are omitted from active reads; detail/include_archived preserve them |
| Historical published mappings | After archiving the mapped question, skill archival succeeded while its published mapping and private rubric remained unchanged; admin published history stayed readable |
| Mapping/archive concurrency | Question reference validation held the skill lock while an archive waited; mapping committed first and archive rejected with SKILL_IN_USE, leaving skill active and graph revision unchanged |
| Bounded coherent reads | Catalog ordering/cursors/filter binding/limits passed; graph and directed/depth neighborhoods passed; node/edge overflow returned GRAPH_READ_LIMIT without a partial graph; static graph route was not swallowed by UUID parsing |
| Guidance rather than access restriction | A published mapped question remained publicly retrievable after adding a prerequisite; no mastery/auth gate was introduced |
| Public/private boundaries | Skill detail/catalog/graph and published-question responses excluded private test/hint/solution/rubric sentinels; existing question privacy/immutability/verifier tests continued to pass |
| Migration from existing data | Real 0002 curriculum/skill/draft/mapping data survived upgrade with revision defaults; ORM metadata matched; replay and downgrade/re-upgrade retained mappings and skill content |

Initial focused tests exposed SQLAlchemy 2.1 deprecation warnings; result handling
was corrected before the final warnings-as-errors run. After the temporary `/tmp`
PostgreSQL installation disappeared, a subsequent run failed at database setup
with connection-refused errors. A fresh user-owned PostgreSQL 18.6 instance was
extracted into `/tmp` and the final suite/migrations were rerun successfully.
Restricted sandbox DNS also blocked the first build-backend resolution; the
network-enabled build then passed. Failed/setup-only runs are not counted as
verification. Database/TestClient checks required execution outside the restrictive
sandbox; no system database installation was changed.

## Contract choices and unverified limits

The decision specifies formerly ambiguous neighborhood bounds/directions, stable
skill ordering, permanent validated archival, revision increments for node edits,
full incoming-set PUT and DELETE revision/204 behavior. Curriculum CRUD/status,
general graph file import, related-topic links, persisted admin audit events and
caching remain future work. DAG/lifecycle validity depends on using the serialized
service; FK/uniqueness/self-link constraints also protect direct SQL, but arbitrary
SQL graph writers are not advertised as cycle-safe. Large-curriculum load/latency
benchmarks were not run; bounded reads and small real concurrency checks passed.

**Production publication remains unavailable until a trusted verifier is
implemented.** Injected verifiers remain test-only and validate transition logic,
not executable correctness or the security/correctness of a future verifier.
Production authentication/startup remain disabled. No recommendation generation,
mastery calculation, timer, submission or code execution was added.

Remote CI, Docker setup and a fresh Windows/WSL setup were not run and remain
unverified. Local Linux regression, real PostgreSQL migrations/integration, static
checks and package checks passed. The commit uses the already configured Git
identity; no author identity was invented or changed.

## Subsequent B3 slice

Owned attempts and server timers are verified separately in [B3 verification](B3_Verification.md).
The B2 checks above remain historical. Trusted-verifier/deployed-authentication
limitations still apply.
