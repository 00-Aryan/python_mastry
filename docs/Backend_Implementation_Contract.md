# Python Mastery Platform Backend Implementation Contract

Version 1.0 · 9 October 2026 · Prepared for Aryan Kumar

Implementation status: B0 and the B1 database/question-storage increments are
implemented locally. [Question storage decisions](decisions/0003_question_storage.md)
record concrete input formats, lifecycle/authorization choices and the user's
publication boundary: no publication until trusted executable verification exists.
The remaining sections retain the broader planning scope.

## 1 Purpose and implementation boundary

We will implement one complete learning branch using a backend whose rules, data and failures can be inspected. This contract supplements the Python Mastery Platform Master Blueprint. It turns the product direction into proposed engineering decisions. It does not claim that application code, dependency installation or a working server has already been created or tested.

The next coding increment is project setup, a migration, question storage and skill-graph validation. Timers, submissions and evidence follow in small tested increments. The full platform is not one initial coding task.

Your engineering instructions are preserved in the companion `AGENTS.md`. Copy it to the repository root when implementation begins. It is project guidance, not an installed ChatGPT skill.

## 2 Recommended stack and explicit choices

| Concern | Initial choice | Reason and limit |
|---|---|---|
| Runtime | Python 3.12 on Linux or WSL2 | A conservative project target, not a claim about the latest Python; verify package compatibility during setup |
| Environment | uv with pyproject.toml, uv.lock and .python-version | Reproducible setup; commit the lockfile; do not manage an additional independent requirements list |
| API | FastAPI and Pydantic v2 | Typed HTTP contracts and generated API documentation |
| Persistence | PostgreSQL | Use the same database semantics locally and in integration tests |
| Data access | SQLAlchemy 2, synchronous Session and psycopg 3 | Straightforward transaction tracing; normal def endpoints for this blocking I/O path |
| Migrations | Alembic | Reviewed, versioned schema changes; no create_all on production startup |
| Tests | pytest, pytest-cov, HTTPX, Hypothesis | Unit, API, integration and property tests |
| Quality | Ruff and mypy | Formatting, linting and type checks alongside behavioral tests |
| Statistical intervals | scipy.stats.beta when Bayesian summaries are added | Use a tested numerical implementation for quantiles |
| Execution | Separate isolated runner behind an adapter | Never execute learner code in the API process |
| Jobs initially | PostgreSQL job/outbox tables and one worker | Durable work without requiring Redis or a broker immediately |

This is our recommended design. Official tool documentation supports the underlying mechanisms, but it does not prescribe this product architecture. We will verify actual versions during installation and let uv resolve a lockfile rather than inventing exact package versions here.

Do not mix synchronous database calls into async endpoints without explicitly moving work off the event loop. If later requirements justify asynchronous SQLAlchemy, migrate the entire relevant boundary and use one AsyncSession per task. Async syntax alone does not solve scalability.

## 3 Architecture and layer responsibilities

Use a modular monolith: one deployable API, organized by capability, and a separate execution worker. Keep four boundaries clear.

| Boundary | Owns | Must avoid |
|---|---|---|
| API presentation | Request validation, authenticated principal, status codes, response DTOs | Timer algorithms, mastery formulas, raw SQL |
| Application services | Use cases, authorization, transactions and coordination | HTTP-specific types and learner-code execution |
| Domain policies | Timer math, valid state transitions, DAG checks, evidence eligibility, ranking | Database sessions, network calls and hidden global state |
| Infrastructure | ORM, repositories, runner client, logging and settings | Deciding mastery or changing pedagogical rules |

The frontend is a separate view layer. The backend presentation layer is the HTTP adapter, not a second frontend. Domain objects need not mirror every database table; use plain dataclasses or typed value objects for rules that benefit from them.

The service owns the transaction. Repositories query, add and flush as requested; they do not commit independently. Inject a database session, clock, ID generator and runner interface where needed. Avoid a generic base repository, service class hierarchy or custom framework that hides simple behavior.

A traceable use case is: request validation → authenticated owner check → load and lock attempt → reconcile elapsed time → validate command → append event and update current state → commit → serialize response. External execution happens after the job is durably committed.

## 4 Folder and file plan

These are planned paths. Create a file when its behavior is implemented rather than filling the repository with empty stubs.

| Path | Responsibility |
|---|---|
| AGENTS.md | Coding, testing and debugging rules for contributors and coding agents |
| README.md | Setup, run, test and troubleshooting instructions |
| pyproject.toml and uv.lock | Dependencies, tooling and resolved versions |
| .python-version and .env.example | Runtime target and documented configuration names |
| src/mastery_backend/main.py | Build the app, lifespan and router registration |
| src/mastery_backend/settings.py | Validated environment settings |
| src/mastery_backend/api/dependencies.py | Principal, request session and service injection |
| src/mastery_backend/api/error_handlers.py | Domain errors to safe HTTP responses |
| src/mastery_backend/api/routers/ | users.py, skills.py, questions.py, attempts.py and progress.py |
| src/mastery_backend/api/schemas/ | Explicit request and response models by capability |
| src/mastery_backend/application/ | user_service.py, content_service.py, attempt_service.py, evaluation_service.py and recommendation_service.py |
| src/mastery_backend/domain/ | attempt_states.py, timer_policy.py, skill_graph.py, evidence_policy.py, mastery_statistics.py and recommendation_policy.py |
| src/mastery_backend/infrastructure/database/ | session.py, models grouped by capability, and focused repositories |
| src/mastery_backend/infrastructure/runner/ | runner_protocol.py and a controlled adapter |
| src/mastery_backend/infrastructure/observability/ | Structured logging, request context and metrics |
| src/mastery_backend/workers/ | evaluation_worker.py and review_worker.py when needed |
| migrations/versions/ | Reviewed Alembic revisions |
| content/dictionaries/ | Versioned authoring inputs; public and private content separated |
| tests/unit/ | Pure rule tests with controlled clocks |
| tests/integration/ | Real PostgreSQL constraints, transactions and race tests |
| tests/api/ | Authentication, ownership, validation and response tests |
| tests/content/ | Question contracts, reference solutions and incorrect solution checks |
| docs/decisions/ and docs/runbooks/ | Architecture decisions and operational diagnosis |

Use names such as `independent_budget_seconds`, `question_version_id`, `active_elapsed_milliseconds` and `maximum_revealed_step`. Avoid `data2`, `helper`, `manager` or `utils.py` as catch-all destinations. Shared behavior belongs to a named domain concept.

## 5 Identifiers and normalized data

Use UUID primary keys generated by the application. Human-readable codes such as DICT-P03 and PY-DICT-COUNT are unique lookup fields, not foreign keys. Store references as typed UUID foreign keys, not filenames, array positions or display titles. Use UTC-aware PostgreSQL timestamptz timestamps, integer durations and explicit enum-like check constraints.

Core relationships: a user owns attempts; an attempt pins a question version and policy version; a question belongs to a novelty family and has many versions; a question version links to skills and patterns; submissions belong to attempts; evaluations belong to submissions; evidence links evaluations to assessed skills; prerequisite edges connect two skills within a curriculum.

Aim for third normal form for transactional entities: separate independent facts, many-to-many mappings and repeated records. JSONB is appropriate for a versioned input contract or structured test data. It must not replace relational ownership, skill links, attempts or prerequisite edges.

### Identity tables

| Table | Important columns and constraints |
|---|---|
| users | id PK; normalized_email UNIQUE when present; display_name; status; created_at; updated_at |
| user_settings | user_id PK/FK; timezone_name; hint_delivery_mode; defaults in seconds |
| authentication_sessions | id PK; user_id FK; token_hash UNIQUE; expires_at; revoked_at; created_at |
| user_roles | composite PK(user_id, role); explicit learner and content_admin assignments |

The local-only first increment can seed one developer identity through a CLI and inject it only in development. A startup guard must reject that authentication mode outside development. No endpoint should trust a learner-supplied user_id as authentication. Add real login before hosting or supporting multiple users. Prefer a reputable OIDC provider when deployment is selected; an opaque server session is sufficient as the application session contract. Store hashes of random session tokens, never raw tokens. Cookie transport requires HttpOnly, Secure in deployment, appropriate SameSite and CSRF protection.

### Curriculum and content tables

| Table | Important columns and constraints |
|---|---|
| curricula | id PK; code UNIQUE; title; graph_revision; status |
| skills | id PK; curriculum_id FK; code; title; competency; archived_at; UNIQUE(curriculum_id, code); UNIQUE(id, curriculum_id) for composite edge FKs |
| skill_prerequisites | composite PK(prerequisite_skill_id, dependent_skill_id); two FKs; CHECK distinct IDs; curriculum_id; composite FKs to enforce same curriculum |
| skill_relations | two skill FKs plus relation_type; UNIQUE pair/type; separate from prerequisite edges |
| patterns | id PK; code UNIQUE; title |
| question_families | id PK; code UNIQUE; novelty definition |
| questions | id PK; code UNIQUE; family_id FK; archived_at |
| question_versions | id PK; question_id FK; version_number; status; statement; contract_json; difficulty; role; suggested_budget_seconds; published_at; UNIQUE(question_id, version_number) |
| question_version_skills | composite PK(version_id, skill_id); attribution_role; rubric_json; UNIQUE primary attribution per version through a partial index |
| question_version_patterns | composite PK(version_id, pattern_id) |
| question_examples | id PK; version_id FK; position; input_json; output_json; explanation; UNIQUE(version_id, position) |
| question_test_cases | id PK; version_id FK; visibility; input_json; expected_json; assertion_rule; critical flag |
| question_assistance_steps | id PK; version_id FK; position; kind; content; next_budget_seconds; UNIQUE(version_id, position) |
| question_solutions | version_id PK/FK; reference_code; explanation; expected_complexity |
| question_links | source_version_id and target_version_id FKs; link_type; UNIQUE pair/type |
| learning_policy_versions | id PK; version_code UNIQUE; immutable configuration_json; effective_at |

Question content in Git is an authoring input. An import command validates it and creates database drafts; the published database version is the runtime authority. The importer uses code and version number to be idempotent and refuses different bytes for an existing published version. Publication freezes statement, tests, hints, mappings and solution together. The active published version is the highest published version_number for a nonarchived question; index that lookup rather than maintaining a second ambiguous source of truth.

Private tests and solutions must be absent from learner response DTOs and early payloads. Restrict their repository access to authoring and evaluation paths. UUIDs provide identification, not authorization.

### Attempts and evaluation tables

| Table | Important columns and constraints |
|---|---|
| attempts | id PK; user_id FK; question_version_id FK; policy_version_id FK; mode; lifecycle_state; assistance_level; revision; started_at; finished_at |
| attempt_phases | id PK; attempt_id FK; phase_number; kind; budget_seconds; active_elapsed_ms; running_since; expired_at; UNIQUE(attempt_id, phase_number); at most one open phase |
| attempt_events | id PK; attempt_id FK; sequence_number; event_type; occurred_at; payload_json; command_id; UNIQUE(attempt_id, sequence_number) |
| attempt_drafts | attempt_id PK/FK; source_code; code_revision; updated_at |
| assistance_deliveries | id PK; attempt_id FK; step_id FK; delivered_at; UNIQUE(attempt_id, step_id) |
| submissions | id PK; attempt_id FK; source_code; code_hash; purpose; accepted_at; accepted_event_sequence; assistance_at_submission; policy context |
| evaluation_jobs | id PK; submission_id FK UNIQUE; status; lease_until; retry_count; next_retry_at |
| evaluations | id PK; submission_id FK; evaluator_version; status; test_summary_json; finished_at; retry generation |
| assessment_checkpoints | id PK; attempt_id FK UNIQUE; status; reason; independent_result; evidence_eligible; snapshot_json |
| skill_evidence | id PK; checkpoint_id FK; skill_id FK; stratum; result; policy_version_id; UNIQUE(checkpoint_id, skill_id) |
| user_question_family_history | composite PK(user_id, family_id); first_attempt_at; first_assistance_at; first_solution_at; updated_at |
| review_tasks | id PK; user_id FK; skill_id FK; question_version_id FK; due_at; interval_stage; status; source_checkpoint_id FK |
| idempotency_records | principal_id; operation; key; request_hash; response_json; expires_at; composite UNIQUE principal/operation/key |

One question attempt may include many runs and submissions. One independent assessment checkpoint supplies at most one Bernoulli observation for a skill, not one observation for every Run click. Do not cascade-delete published content or attempts. Restrict deletion and archive content. User erasure is a separate reviewed operation covering drafts, logs and backups under a documented retention policy.

### Derived and audit tables added when needed

When adding skill_evidence, persist its user_id, family_id and observation_kind from the checkpoint context to support an enforceable unique initial-observation index. These immutable attribution fields are a deliberate denormalization; derive them only from verified foreign-key relationships. Policy recalculation must not let one attempt count twice within the same statistics version.

`skill_statistics` is a rebuildable projection keyed by user, skill, difficulty, assessment mode and policy version. It stores counts and computed_at, not an authoritative mastery fact. `recommendation_runs` records candidate IDs, reasons and rule version. `outbox_messages` stores durable follow-up work in the same transaction as domain writes. `admin_audit_events` records publication, graph changes and administrative actions.

Do not build every projection in the first increment. Introduce schema groups when their use case starts, preserving these relationships.

## 6 CRUD rules and endpoint contracts

Prefix APIs with `/api/v1`. Use cursor pagination for growing history, stable ordering by created_at plus id, a default limit of 20 and maximum of 100. Every user-owned query includes the authenticated owner predicate. Unknown or inaccessible resources return a consistent 404; admin routes additionally require the relevant role.

| Resource | Create | Read | Update | Delete |
|---|---|---|---|---|
| User | CLI seed first; login/provider flow later | GET /me | PATCH /me and /me/settings | Dedicated account erasure later |
| Skill | POST /admin/skills | GET /skills and /skills/{id} | PATCH with revision check | Archive; remove draft edges through graph service |
| Prerequisite | POST /admin/skills/{id}/prerequisites | GET /skills/graph | Validated edge change transaction | DELETE edge through same graph lock |
| Question | POST /admin/questions plus draft version | GET /questions and /questions/{id} | PATCH draft; create new version after publication | Delete unreferenced draft or archive question |
| Publication | POST /admin/question-versions/{id}/publish | Admin content preview | Immutable after publish | No ordinary deletion |
| Attempt | POST /attempts with version, mode and budget | GET /attempts/{id} and history | Explicit pause/resume/extend/defer commands | No learner deletion of assessment history |
| Draft | Initialized with attempt | GET as part of owned attempt | PUT /attempts/{id}/draft with code revision | Erasure policy only |
| Hint | POST /attempts/{id}/assistance/next | Only delivered content | Append-only delivery | Never erase assistance history to restore U credit |
| Submission | POST /attempts/{id}/submissions | GET /submissions/{id} | Worker status transition | Immutable code snapshot |
| Progress | Service-derived | GET /progress and /recommendations | Rebuild internally | No manual mastery PATCH |

API error body: code, message, request_id and safe details. Use 422 for invalid input, 401 for absent identity, 403 for role denial, 404 for absent/owned-resource lookup, 409 for stale revision, duplicate incompatible idempotency key, illegal state or graph cycle, and 503 for retryable dependencies. Infrastructure errors do not become learner failures.

POST commands accept an Idempotency-Key. A repeated key with identical payload returns its recorded result; a different payload returns 409. Do not cache transient failures as successful command results. Apply optimistic revisions to drafts and configuration; serialize attempt-changing commands with a row lock. Never hold a DB transaction while running code or waiting for a network call.

## 7 State model and transaction boundaries

Separate lifecycle, assistance and evaluation status rather than creating dozens of combined states.

- Lifecycle: active, paused, completed, deferred, abandoned.
- Assistance: none, directional, pattern, pseudocode, partial_code, full_solution.
- Evaluation: pending, running, passed, failed, infrastructure_error.
- Expiry: per-phase timestamp; it is not automatically a learner failure.

Start creates an attempt, a phase and an event atomically. Pause, resume, extend and reveal lock the owned attempt, reconcile its clock, validate state and revision, append events and update the current projection atomically. A stale competing command either becomes an idempotent replay or a 409 conflict.

Submit stores immutable source and a durable job in one transaction. The worker leases a job, executes outside the transaction, and commits results with an evaluation generation/token so an expired old lease cannot overwrite newer work. Apply checkpoint/evidence and review creation idempotently. If the worker crashes after execution but before commit, rerun the job safely.

While an assessment submission is pending, do not deliver new assistance or accept another assessment submission. Countdown accounting continues; expiry records eligibility for a hint. After resolution, a passing pre-assistance submission can finish independently. A failed result allows further coding or help. This avoids a hint/submission race altering the classification of code already submitted. Learners can still retrieve saved code and job status. Bound evaluation time and surface delayed-job errors so this is not an indefinite lock.

## 8 Server-owned time storage and calculation

The browser displays a countdown but never decides stored elapsed time or evidence. Inject a `Clock` in pure tests and use one authoritative server timestamp per transaction. Assume synchronized server clocks; detect large backward jumps and do not allow negative elapsed durations.

Timer state is per attempt and per phase. Also retain the learner’s total active solving duration through pause/resume events so overdue time remains visible separately from the capped countdown. On expiry, freeze the phase at its budget boundary; any further active solving time is recorded as overdue time until the next phase starts. This avoids confusing a hint interval with total working time.

For a running phase before expiry:

```
additional_elapsed_ms = max(0, now - running_since) in milliseconds, if running
phase_elapsed_ms = stored_active_elapsed_ms + additional_elapsed_ms
remaining_ms = max(0, budget_seconds * 1000 - phase_elapsed_ms)
```

Pause materializes elapsed time and clears running_since. Resume sets running_since to now. Repeated pause or resume is idempotent or returns an explicit state conflict; it must not add elapsed time twice. Extension increases budget only before phase expiry, within configured bounds, and records its amount and reason. Once assistance has been delivered, extension cannot erase that history.

A server response contains server_now, phase_started_at, remaining_ms, phase budget, lifecycle and revision. The frontend uses its monotonic clock for animation, resynchronizes periodically and after reconnection, and never sends authoritative elapsed seconds. It need not write to the DB every second.

Browser closure does not imply pause. A running phase continues until a confirmed pause or expiry. Offline pause requests take effect only when accepted by the server. Document that UX behavior. Explicit pauses exclude time from practice timers; stricter timed-assessment mode records pauses as a timing accommodation so those results are not mixed with strict interview timing.

At budget expiry, mark the phase expired. The connected client invokes an idempotent reveal command or receives a notification and then retrieves the authorized step. Persist delivery before returning hint content. This is a conservative record that content was disclosed; a server cannot prove the learner visually read it. Merely scheduling expiry or unlocking eligibility is not disclosure. Automatic first-hint mode applies only while connected; later stages require a further attempt interval or an explicit request.

Returning to an expired offline attempt offers or delivers the configured first hint exactly once. Expiry reconciliation occurs before commands and reads that expose time-sensitive state; later add a due-phase sweeper for notifications. GET requests must not themselves deliver private hint content or create mastery evidence. No sleeping request, process-local countdown or per-second database update is required.

## 9 DAG persistence and validation

Store prerequisite → dependent edges in the relational table. Keep related-topic, pattern and review links outside this DAG. There is no need for a graph database for a small curriculum.

To add edge A → B: verify both skills belong to the same curriculum and are active; reject A = B; lock the curriculum row; load the relevant current graph; reject the edge if B can already reach A; insert; increment graph_revision; commit. Every add/remove/bulk import follows the same lock order. Without a shared lock, two concurrent individually valid additions can create a cycle.

Use adjacency lists and DFS/BFS for reachability and Kahn’s algorithm or DFS for whole-graph cycle validation. Complexity is O(V + E). Return a meaningful cycle path with skill codes. For bulk imports validate the resulting graph as a whole, not only each proposed edge against the old snapshot.

Cache graph data only by curriculum ID and committed graph_revision if measurement later warrants it. Never depend on a process-local cache to enforce graph integrity. Tests include disconnected nodes, multiple parents, diamonds, self-links, duplicate edges, cross-curriculum links, long cycles and concurrent inverse additions.

Prerequisites affect recommendations, not authorization to attempt a published available question. An admin may archive a skill only through validation of affected content and edges; historical evidence remains accessible.

## 10 Evidence eligibility and calculations

Start with deterministic policies. Separate completion, independent assessment, retention and timing. Version the policy and save the inputs used for each decision.

An eligible independent observation requires an assessment task with identifiable primary skill, a previously unseen question family for that initial-skill stratum, a valid completed independent segment, and an outcome under comparable conditions. A guided practice task, exposed solution, incomplete attempt, infrastructure failure or ordinary repeat supplies no new Bernoulli observation.

Record family exposure at attempt start and snapshot whether the family was previously attempted or assisted before inserting that exposure. Merely opening a problem statement is not solution disclosure, but repeating an attempted task is familiar. At start, lock the user/family history boundary so concurrent attempts cannot both claim first exposure. A family groups questions with substantially the same solution, not all questions sharing a Python concept. A transfer question must change the demands enough to belong to a distinct assessment family.

Only one checkpoint per attempt, and only the first eligible initial assessment per user/family/stratum contributes to initial Bayesian statistics. Enforce an additional unique observation key including user_id, family_id, skill_id, stratum and policy_version; do not rely only on checking before insert. Reserve later review evidence for retention reporting, not independent iid observations. A multi-skill task contributes only where its rubric provides separately observable evidence; initially use one primary assessed skill.

A correct submission before any help gives y = 1. An explicitly closed independent segment that required help or ended unresolved gives y = 0 only if there was a valid attempt, such as a submitted implementation or recorded explicit stuck conclusion. Asking for teaching immediately, mere expiry or browser abandonment is incomplete/excluded, not automatically a failure. Intermediate failed tests during debugging are not additional observations. Assistance logs and immutable submission snapshots determine classification; client-provided U/H/F labels are never accepted as facts.

For fixed skill, difficulty, assessment mode and policy stratum:

```
alpha_posterior = alpha_prior + independent_success_count
beta_posterior = beta_prior + independent_failure_count
posterior_mean = alpha_posterior / (alpha_posterior + beta_posterior)
posterior_variance = alpha_posterior * beta_posterior / (
    (alpha_posterior + beta_posterior) ** 2
    * (alpha_posterior + beta_posterior + 1)
)
credible_interval_90 = (
    beta_distribution.ppf(0.05, alpha_posterior, beta_posterior),
    beta_distribution.ppf(0.95, alpha_posterior, beta_posterior),
)
```

Require positive finite prior parameters and nonnegative integer counts. For illustrative Beta(2,2), U=5 and F=3 gives Beta(7,5), mean 7/12 ≈ 0.583333. With no evidence, the mean is a prior, not a learner rating. Suppress persuasive mastery percentages when evidence is sparse and report eligible counts, uncertainty and exclusions.

This is a stationary baseline, not a model of rapidly changing ability. Do not give fractional success credit for hints or blindly combine difficulties. Current retention comes from recent unseen reviews; a cumulative posterior cannot alone decide mastery. Bayesian summaries are introduced after the attempt loop, as the master blueprint specifies.

Level 3 provisionally requires an unseen independent assessment and independent transfer evidence. Retained competence additionally needs a delayed success. Level 4 additionally requires a mixed timed task and a sufficient explanation. Code tests cannot certify explanation quality; use a reviewed rubric or leave that component pending. Store unmet criteria and source IDs, not just a boolean tick.

## 11 Recommendation and review rules

Use a lexicographic priority order rather than an arbitrary sum of incompatible quantities: due review → observed prerequisite/language gap → targeted repair after assistance → uncertainty diagnostic → transfer → challenge. The learner can override. Within a priority tier, choose relevant available questions using unmet skills, novelty, appropriate difficulty and stable ID tie-breaking. Store the rule version, reason code, evidence IDs and alternatives.

Initial reviews: schedule an unseen review for +3 days after assisted/failed practice; schedule a +10-day variation from the source completion as the initial policy. If the +3-day review fails, prioritize repair and a new review +3 days from repair completion rather than treating the original +10 day slot as proof of readiness. Successful retention checks can move to a wider future interval after calibration.

Store due_at in UTC plus user timezone and original local scheduling date. Interpret day-based intervals in the learner’s timezone; use a configurable local review time such as 09:00. A background worker computes due work, while the API can also query due tasks directly. Deduplicate review creation by source checkpoint, skill and interval stage. Keep historical scheduling changes for diagnosis.

No FSRS, BKT, IRT or bandit dependencies initially. Add a model only after defining its prediction target, calibration data and comparison with existing rules.

## 12 Debugging and observability

Use structured JSON logs with request_id, operation, attempt_id, submission_id, job_id, graph_revision and policy_version where applicable. Return request_id on errors and preserve it through job/outbox payloads. Log state_before/state_after, reason codes and durations at key boundaries. Capture unexpected exceptions with stack traces once at the boundary, then return a safe error.

Never log credentials, tokens, full learner code or private solutions by default. Code is available to authorized inspection through its stored immutable submission. Differentiate learner SyntaxError/test failure from runner infrastructure errors and application exceptions.

Metrics: HTTP error rate and latency, DB pool waits, job queue age, worker retry count, evaluator failures, graph conflicts and evidence exclusions. Health checks distinguish process liveness from database/worker readiness. A failed background job should not falsely make every API route unavailable.

Debug runbook: find request_id → inspect command and attempt revision → reconstruct ordered events and phase clocks → inspect submission and evaluator version → inspect policy inputs and eligibility reason → reproduce with a sanitized fixture and fixed clock → add regression test → fix → replay affected projections if necessary. Store reason codes such as PRIOR_ASSISTANCE, FAMILIAR_FAMILY, INCOMPLETE_SEGMENT, EVALUATOR_UNAVAILABLE and STALE_REVISION.

## 13 Security and data boundaries

Authorize every owned resource, even when referenced indirectly through a submission or review. Validate input sizes, durations, code length, page limits and JSON depth. Parameterize SQL through ORM/query APIs. Use least-privilege credentials; content-admin access is separate from learner access.

Code execution is a release-critical subsystem. A subprocess timeout, restricted builtins or eval wrapper is not an adequate sandbox. The runner needs unprivileged execution, resource limits, bounded output, controlled mounts and no API/database credentials. Hidden-test secrecy also needs a defined trust boundary: learner code must not inspect the harness, expected outputs or test files. Prefer a runner that calls the submitted function through a controlled protocol and compares outputs outside the learner context. Test introspection and file/network escape attempts before accepting arbitrary untrusted code.

Use a fake deterministic runner only for backend orchestration tests and a prototype explicitly labelled unevaluated. It cannot produce real mastery credit. Do not ship an unsafe runner to finish a feature faster.

Document backup, restore and erasure behavior before real user data is hosted. Verify restoration on a test database; having a backup file is not evidence that recovery works.

## 14 Scalability without premature distribution

Index owner/history queries `(user_id, created_at, id)`, question publication lookup, incoming/outgoing prerequisite edges, due reviews, and pending jobs. Verify query plans with representative data. Use bounded queries and select-in loading where appropriate to avoid N+1 behavior.

API workers can scale horizontally because current state, idempotency and jobs live in PostgreSQL. Bound worker concurrency and connection pools; budget total connections across all processes. Do not create a connection per countdown tick. Move large code snapshots or assets to object storage only after measured size/retention pressure, retaining transactional references and content hashes.

Database jobs use short lease transactions and appropriate locked-row claiming. Workers are at-least-once, so result application is idempotent. Use bounded retries with backoff for transient outages; invalid content is not retried forever. Keep dead/failed jobs inspectable. Introduce a broker, cache, partitioning or separate service only when concrete latency, throughput or ownership requirements justify it.

## 15 WSL and uv setup procedure

Run commands inside the Linux shell, not Windows Python. Keep the project under a WSL Linux path such as `~/projects/python-mastery-backend`. Open VS Code using its WSL integration and choose `.venv/bin/python`. Avoid sharing a virtual environment between Windows and Linux.

Install uv using the official installation instructions. The following are planned commands for the implementation increment, not commands executed or verified in this planning turn:

```bash
mkdir -p ~/projects
cd ~/projects
uv python install 3.12
uv init --package --python 3.12 python-mastery-backend
cd python-mastery-backend
uv python pin 3.12
uv add fastapi 'uvicorn[standard]' 'sqlalchemy>=2,<3' 'psycopg[binary]' alembic pydantic-settings
uv add --dev pytest pytest-cov httpx hypothesis ruff mypy
uv sync
```

Choose the package directory `mastery_backend` explicitly during bootstrap and align packaging settings. The default generated name may differ; the runnable import path must match the directory, not a copied example. Add SciPy in the Bayesian increment. Add an authentication provider library when the provider is selected.

Use PostgreSQL installed natively inside WSL or one local container. On a resource-constrained laptop, begin with one API process and one DB instance; avoid several orchestration services. Native/container startup commands depend on the chosen installation and should be documented when set up, rather than guessed here.

Configuration names: APP_ENV, DATABASE_URL, TEST_DATABASE_URL, LOG_LEVEL, ALLOWED_ORIGINS, AUTH_MODE, RUNNER_URL, MAX_CODE_BYTES and EVALUATION_TIMEOUT_SECONDS. Keep secrets in ignored `.env`; commit `.env.example` with placeholders. Settings validation should fail early and name the missing variable without printing secret values.

Once the corresponding files exist, the development loop is:

```bash
uv sync --locked
uv run alembic upgrade head
uv run uvicorn mastery_backend.main:create_app --factory --reload
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy src
```

Use a separate test database and fail closed if TEST_DATABASE_URL points at the ordinary development/production DB. Commit reviewed migrations, uv.lock and pyproject.toml. Record uv and DB versions in the setup guide; upgrades are deliberate changes with checks, not silent installation drift.

## 16 Testing contract for every implementation increment

Every behavior we implement must have meaningful tests in the same increment. A declaration-only file is covered through the behavior that uses it; avoid fake one-test-per-line rules. All business-rule modules, API boundaries, repositories with nontrivial queries, migrations and worker transitions need corresponding checks.

| Area | Required test examples |
|---|---|
| Timer | Exact expiry, pause/resume, repeated pause, extension boundary, negative clock jump, reload, offline closure |
| Attempt state | Illegal commands, terminal states, retry keys, concurrent hint/submit, stale revisions |
| Content | Reference solution passes; common wrong answers fail; hint order; public response excludes secrets |
| DAG | Self/duplicate/cycle/diamond/disconnected cases; concurrent inverse edge insertion |
| Statistics | Beta(7,5) example, zero evidence, invalid prior, excluded repeats, difficulty separation and interval ordering |
| CRUD | Ownership checks, admin role, pagination, conflict, draft deletion and published immutability |
| Database | Real FK/check/unique constraints, rollback, row locks, independent sessions and migration upgrade |
| Workers | Crash after lease, retry after result, stale lease, timeout, duplicate delivery and no double evidence |
| Authentication | Development guard, session expiry/revocation and no caller-selected identity |
| Observability | Request ID propagated, safe error shape, secret redaction and reason codes |

Use pure unit tests with a fake clock for algorithms. Use actual PostgreSQL for transaction/concurrency tests; SQLite cannot establish PostgreSQL locking behavior. API tests override dependencies deliberately. Property tests check DAG and timing invariants across generated inputs. Keep runner integration tests separate from orchestration tests.

A new bug starts with a reproducing test. Each change report states which tests ran and what remains unverified. Coverage helps find missing branches but a numeric target alone is not acceptance. No arbitrary sleep-based timer tests when a controlled clock will work.

## 17 Ordered implementation backlog

| Increment | Build | Completion condition |
|---|---|---|
| B0 | uv package, validated settings, app factory, test configuration, logging and health | Fresh WSL setup documented; smoke, settings and error tests pass |
| B1 | PostgreSQL migration for skills, draft/published questions and seed identity; focused CRUD | Constraints, ownership/admin restrictions and publication tests pass |
| B2 | Prerequisite DAG service and import validation | Cycle and real concurrency tests pass; graph revision is consistent |
| B3 | Attempts, phases, drafts, server time, idempotent commands and staged help | Reload and race tests pass; no help exposure can disappear |
| B4 | Immutable submissions, durable jobs and isolated evaluator adapter | Execution trust boundary verified; infrastructure errors excluded from learner evidence |
| B5 | Checkpoints, evidence, review tasks and transparent recommendations | No duplicate observations; eligibility decisions explainable |
| B6 | Bayesian summaries and projection rebuild | Mathematical cases, exclusions and rebuild equivalence pass |
| B7 | Pilot improvements and next topic | Real attempts identify gaps; adding content reuses the established flow |

B0–B3 can progress without a production code runner. Real automatic correctness and mastery gates wait for B4. No phase should silently substitute hand-authored success results for executed evaluations.

## 18 Decisions and open deployment details

Chosen direction: uv, WSL/Linux, a modular monolith, separate execution, PostgreSQL semantics, server-owned time, versioned content, explicit commands, evidence provenance and tests accompanying code.

Remaining deployment choices: hosting, authentication provider, secure runner technology and resource budget. These do not block B0–B2. Dependency compatibility, installed PostgreSQL and actual startup commands are verified during implementation. No document can eliminate bugs; deterministic rules, provenance, logs and regression tests make causes recoverable.

## 19 Official references checked for this contract

- uv project workflow and lockfiles: https://docs.astral.sh/uv/guides/projects/
- FastAPI synchronous and asynchronous operation: https://fastapi.tiangolo.com/async/
- SQLAlchemy session and transaction scope: https://docs.sqlalchemy.org/en/20/orm/session_basics.html
- PostgreSQL constraints: https://www.postgresql.org/docs/current/ddl-constraints.html
- PostgreSQL transaction isolation: https://www.postgresql.org/docs/current/transaction-iso.html
- SciPy Beta distribution and quantiles: https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.beta.html
- Microsoft WSL environment guidance: https://learn.microsoft.com/en-us/windows/wsl/setup/environment

These references ground tool behavior. Schema, timing, eligibility and delivery choices above are product-specific proposals, not claims made by those documentation authors.

## Released assistance storage refinement (user-requested B4)

The incremental release numbering now calls progressive assistance B4. The original
submission/evaluator backlog entry remains future work. The authoritative implemented
rules are [decision 0006](decisions/0006_progressive_assistance.md) and the
[B4 API slice](REST_API_Settings_and_Contract.md#released-b4-progressive-assistance-10-october-2026).

Reuse immutable question_assistance_steps/question_solutions and attempt policy/version
pins. assistance_grants replaces the planned assistance_deliveries name: each fact
records attempt_id/step_id, granted_at, reason, command_id, operation/key/request hash
and an immutable original response for indefinite retry recovery. Unique attempt/step
and attempt/operation/key prevent duplicate grants. PostgreSQL guards enforce immutable
grants, pinned assets and monotonic assistance projections. This fact says content was
granted, not that a learner read it; no read timestamp or mastery observation is added.

New attempts pin pilot-assistance-1; timer-only B3 attempts keep their old policy and
deny new assistance safely. Subsequent assistance phases are numbered above zero;
prior_phase_elapsed_ms preserves accumulated work in closed phases for correct total
versus overdue projections. First early help closes the independent interval permanently.
Pause/resume/extend cannot erase exposure; defer/abandon prohibit new grants. Explicit
confirmed full-solution escape closes the current interval without ending the session.
All waiting intervals use the existing injected server clock and persisted phase anchors,
with no background sleeps or per-tick writes. Transaction/ownership/revision/idempotency
boundaries match B3. API/services/domain/repositories retain separate responsibilities.

Public catalog/attempt projections never load assistance bodies. Dedicated owned
commands/history return only granted assets. Stored grant receipts duplicate the response
intentionally for exact recovery; authoritative content remains the pinned published
asset. History is separate from any future scoring or evidence calculations. No code
submission, execution, automatic correctness, recommendation or mastery path is released.

## Released immutable receipt refinement (user-requested B5)

[Decision 0007](decisions/0007_immutable_submissions.md) and the
[B5 API slice](REST_API_Settings_and_Contract.md#released-b5-immutable-source-receipts-10-october-2026)
refine the original submission backlog into a receipt-only increment. submissions
stores exact source/hash/bytes, attempt/question/policy/phase pins, acceptance time,
acceptance event sequence/revision, immutable evidence_json and an attempt-scoped
request key/hash. Unique request/event constraints, restrictive FKs, byte/hash checks
and PostgreSQL insert/history guards accompany application validation.

Every intake locks the database user then owned attempt, reconciles exact expiry,
materializes timer anchors and captures timer/assistance/context evidence with its
submission_received event in one transaction. This uses the same total ordering as
help/timer transitions; later grants cannot rewrite earlier snapshots. Assistance
IDs are recorded without loading hint or solution text. The original response can
be reconstructed indefinitely for retry without a duplicate general command receipt.
Acceptance-time evidence is input for future rules, not an eligibility outcome.

No evaluation_jobs, evaluations or checkpoints are created. received/not_requested
accurately describe receipt rather than pending execution. Consequently the future
pending-assessment help lock is not activated; active/paused learners may continue
submitting or requesting help. Both purpose values remain intent only. Invalid
Python syntax is stored rather than classified by the API. All execution must await
a verified isolated runner, and no receipt can award correctness or mastery.

Owned detail includes submitted source; bounded attempt lists select metadata only.
Archived pinned content remains available to its existing owner. Source/evidence and
retry facts are immutable, and downgrade refuses stored receipts. Payload limits,
strict authorization and safe logging remain the infrastructure/API boundaries.

## Released evaluation orchestration refinement (user-requested B6a)

[Decision 0008](decisions/0008_evaluation_lifecycle.md) and the
[B6a API slice](REST_API_Settings_and_Contract.md#released-b6a-evaluation-lifecycle-10-october-2026)
are authoritative for this scoped increment. B5 receipt intake stays separate from
owned evaluation admission. Atomicity covers the job, append-only initial transition,
durable dispatch intent and permanent request receipt, alongside the ordered attempt
event/revision. One immutable submission has at most one job; retry generations are
infrastructure redelivery, never extra assessment observations.

Normalized test bundles reference the immutable published assets already stored.
Jobs pin source submission, question, attempt learning policy, bundle and evaluator
policy. Explicit state/history, leases, generations, bounded backoff/deadlines and
current-token result application protect terminal results. The application worker
calls the trusted adapter outside transactions. Shared transition/admission rules
also finalize overdue pending assessments before valid help/assessment commands,
preventing indefinite help locks if the worker stops. Status polls stay read-only.

No supported production adapter, worker daemon, learner-code execution, transport
callback, grader, publication verifier, evidence/checkpoint calculation or mastery
path is enabled. Default requests return 503 EVALUATION_UNAVAILABLE without writes.
Adapter implementations live only in tests; application and worker reject injection
outside APP_ENV=test. Future real runner admission requires authenticated identity/
results and adversarially verified execution isolation. Synthetic outcomes prove
orchestration only, not correctness of source or future runner security.


## Released B6b local execution boundary

B6a's release restrictions above describe its historical baseline. B6b introduces a
separate operator-authenticated local worker, Bubblewrap/systemd/seccomp boundary,
outside-sandbox grading and immutable signed provenance. The API still never executes
source or accepts callbacks. Default admission remains unavailable; only development
with fresh authenticated readiness is allowed. Protocol v2 pins exact runtime/profile
hashes without editing v1 history. Learner-safe runtime/resource failures are distinct
from retryable infrastructure failures. See decision 0009, Local_Runner_Setup and
B6b_Verification for required controls, actual capabilities and remaining limitations.
Publication verifier, deployed authentication, recommendations and mastery are excluded.

### S012 implementation refinement: reference-verification artifacts

[Decision 0010](decisions/0010_publication_artifacts.md) defines a separate local
admin command which captures immutable authored bytes, runs reference code only in
existing B6b isolation outside transactions, and appends a pinned bounded report.
Migration 0009 preserves report history and existing immutable evaluator policies.
Reports are private authoring evidence; they do not publish questions or grant
learner correctness/mastery. API publication remains unavailable until the separate
S013 report-consumption/revalidation increment. Broader quality validation is S014.

### S013 implementation refinement: safe local publication

[Decision 0011](decisions/0011_safe_publication.md) connects the existing two-phase
publication transition to immutable S012 evidence. Explicit approval of an immutable
evaluator-policy ID, exact snapshot/component pins, trusted verifier/version, passing
bounded results and age <24 hours are required. The API reads evidence outside the
authoring transaction and rechecks it with revision/hash/references/archival/admin
under final locks. It never executes code. Missing approval/usable evidence retains
503. Local publication can succeed with accepted evidence; S014 quality validation,
production authentication and remote/deployed certification remain separate.
