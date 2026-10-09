# Python Mastery Platform REST API Settings and Contract

Version 1.0 · 9 October 2026 · Companion to Backend Implementation Contract and AGENTS.md

Implementation status: B0 and the B1 database/question-storage increments are
implemented locally. [Question storage decisions](decisions/0003_question_storage.md)
record concrete input formats, lifecycle/authorization choices and the user's
publication boundary: no publication until trusted executable verification exists.
The remaining sections retain the broader planning scope.

## 1 What an API means in this project

The API is the agreement between the user interface and the backend. The interface sends an HTTP request to start an attempt, save code, request help or submit a solution. The backend checks permissions and rules, updates the database and returns a documented response.

We will use a REST-style JSON API: URLs identify resources, HTTP methods describe the operation, and HTTP status codes describe the request outcome. Explicit action endpoints represent important transitions such as pause or publish. We do not claim strict hypermedia-driven REST compliance. Each request identifies its authenticated principal; durable application login sessions and stored attempts remain server-managed resources.

This document defines proposed implementation contracts. None of these routes is deployed yet. Settings defaults and limits are initial engineering decisions to verify and calibrate, not established product measurements. The backend contract remains authoritative for business rules; this document specifies their HTTP boundary and adds API-specific details.

## 2 Addresses and common conventions

| Setting | Initial contract |
|---|---|
| Development origin | http://localhost:8000 |
| API base path | /api/v1 |
| Example full URL | http://localhost:8000/api/v1/attempts |
| Local bind address | 127.0.0.1; explicitly change only if another device must connect |
| Production address | HTTPS under the selected deployment domain; not selected yet |
| Format | application/json with UTF-8 encoded JSON |
| Field names | snake_case; descriptive names and explicit units |
| Resource identifiers | UUID strings; human-readable question codes are separate fields |
| Times | UTC RFC 3339 timestamps, such as 2026-10-09T04:00:00Z |
| Durations | Integer budget seconds; elapsed and remaining milliseconds |
| Success body | A typed resource object; list responses use items and next_cursor |
| Error body | One consistent error envelope with safe details |
| Trailing slashes | Canonical routes omit them; client uses canonical paths directly |

The browser-facing host should remain consistent: localhost and 127.0.0.1 are different origins for browser configuration. The bind address need not match the browser hostname. Health endpoints and development API documentation sit outside /api/v1.

## 3 Keep three types of settings separate

**Infrastructure settings** live in validated server configuration. Examples are the database URL, CORS origins, log level and request size limit. Secrets are never served through learner endpoints.

**Learning policies** are immutable, versioned database records. They define allowed timer bounds, assistance steps, evidence eligibility, prior parameters and review rules. Each attempt pins a policy version. Changing an environment variable must not retrospectively alter an assessment.

**User preferences** belong to the authenticated user. Examples are timezone, default practice budget and automatic hint versus offer-only behavior. Preferences are bounded by the policy. A preference cannot grant an admin role, erase hints, or extend a strict assessment indefinitely.

A public configuration endpoint returns a deliberately small allowlist of UI-relevant capabilities and supported choices. It never returns the entire Settings object, database connection, runner address, tokens or hidden content.

## 4 Server configuration and initial defaults

| Variable | Type and initial value | Validation or usage |
|---|---|---|
| APP_ENV | development, test or production | Explicit production startup guards |
| DATABASE_URL | Required PostgreSQL connection URL | Secret; fail startup if absent or invalid |
| TEST_DATABASE_URL | Required for integration tests | Must identify a separate test DB; reject ordinary DB target |
| AUTH_MODE | development_identity locally; session when deployed | development_identity rejected outside development/test |
| DEVELOPMENT_USER_ID | Seeded UUID; local mode only | CLI creates user; request cannot choose identity |
| API_HOST | 127.0.0.1 | Launcher supplies it to Uvicorn; not read automatically by Uvicorn |
| API_PORT | 8000 | Integer 1–65535; launcher supplies it |
| ALLOWED_ORIGINS | JSON array of exact frontend origins | Empty until a frontend needs cross-origin access; no wildcard credentials |
| ALLOWED_HOSTS | JSON array; localhost and 127.0.0.1 locally | Distinct from CORS; deployment adds actual domain |
| CORS_ALLOW_CREDENTIALS | true for browser sessions | Require explicit allowed origins |
| API_DOCS_ENABLED | true locally; false by default in production | Deployment may provide protected documentation |
| LOG_LEVEL | INFO | Never print secrets in startup dumps |
| MAX_REQUEST_BODY_BYTES | 262144 | 256 KiB; enforced before full body parsing |
| MAX_CODE_BYTES | 65536 | 64 KiB UTF-8 source limit, including draft saves |
| MAX_PAGE_SIZE | 100 | Default page size remains 20 |
| DB_POOL_SIZE | 5 per API process | Tune total connection budget, not one process alone |
| DB_MAX_OVERFLOW | 5 | Bounded, reviewed with worker pools |
| DB_POOL_TIMEOUT_SECONDS | 5 | Pool exhaustion returns a safe transient error |
| DB_STATEMENT_TIMEOUT_MS | 5000 | Configure explicitly on DB sessions; not merely a Python variable |
| RUNNER_URL | Required only for enabled real evaluation | Server-only internal address |
| EVALUATION_TIMEOUT_SECONDS | 10 initial execution limit | Runner enforces wall time; calibrate per allowed task |
| EVALUATION_MAX_ATTEMPTS | 3 infrastructure retries | Learner test failure is not retried as an outage |
| JOB_LEASE_SECONDS | 30 | Must exceed bounded execution plus result handling, or be renewed safely |
| SESSION_IDLE_TIMEOUT_SECONDS | 86400 proposed | Used when real sessions are introduced |
| SESSION_ABSOLUTE_TIMEOUT_SECONDS | 604800 proposed | Seven days; independent of idle timeout |
| SESSION_COOKIE_SECURE | false only for local HTTP; true deployed | Production must reject insecure session configuration |
| SESSION_COOKIE_SAMESITE | lax initially | Same-site deployment recommended; cross-site design requires review |

CORS methods: GET, POST, PUT, PATCH, DELETE and OPTIONS. Allowed custom headers include Idempotency-Key, X-Request-ID and X-CSRF-Token, alongside Accept and Content-Type. Exposed response headers include X-Request-ID, Location, Retry-After and Idempotency-Replayed. Authentication CORS behavior must be tested before enabling browser sessions.

Environment parsing uses Pydantic Settings. `.env.example` contains placeholders and documented defaults; `.env` is ignored. List values use JSON arrays, not ambiguous comma-separated strings. Load and validate once during app construction, allowing explicit test overrides. Add settings only when their corresponding implementation exists; a declared limit must actually be enforced.

For the initial local API, bind explicitly:

```bash
uv run uvicorn mastery_backend.main:create_app --factory --reload --host 127.0.0.1 --port 8000
```

This is a future run command, usable once the package exists. Live reload belongs to development. TLS and trusted-proxy handling are deployment work; never trust arbitrary forwarded identity or client-IP headers.

## 5 Authentication and authorization

The first local-only increment uses one seeded development identity. It requires no caller-provided user_id and cannot be used for hosting. Its admin permissions come from the seeded roles, never an arbitrary request header. Tests explicitly override the principal dependency.

For deployment, use opaque server sessions in a cookie after a chosen login/OIDC flow. The API stores the hash of the random session token and validates expiry, revocation and user status. The browser sends credentials; the backend derives ownership from the session. No public API key is required for this personal practice application.

Mutating session-authenticated requests need CSRF protection and origin checks. CORS does not authenticate a user and does not replace CSRF protection. Same-origin or same-site deployment reduces cookie complexity. If cross-site frontend/backend hosting is chosen later, revisit cookie SameSite, Secure and CSRF rules before deploying.

GET /me requires a current identity. Admin routes require content_admin. Learner-owned attempts, submissions, reviews and drafts require owner checks in their query path. Return 404 for another user's owned resource, even if its UUID exists. Return 403 for a visible route requiring a role the caller lacks.

Login, provider callback and logout endpoint contracts are deferred until the provider is selected. They are not silently available through the endpoint list below. A logout operation must revoke the application session, not simply remove the frontend cookie.

## 6 Headers and errors

| Header | Contract |
|---|---|
| Accept | application/json for API calls |
| Content-Type | application/json for JSON bodies; malformed JSON is 400, unsupported type is 415 |
| Idempotency-Key | Required on state-changing POST commands; 1–128 printable ASCII characters |
| X-Request-ID | Optional caller trace hint; validated short format, otherwise server generates an ID |
| X-CSRF-Token | Required for unsafe requests in deployed session-cookie mode |
| Location | Returned for created attempt/version and accepted submission resources |
| Retry-After | Returned with rate limits and applicable transient dependency responses |

Error example:

```json
{
  "error": {
    "code": "STALE_REVISION",
    "message": "The attempt changed. Reload its current state and retry.",
    "request_id": "req_8dca3ac7",
    "details": {"current_revision": 4}
  }
}
```

Safe validation details can contain a field path and reason. Never echo rejected learner source, full request bodies, SQL errors, session values, hidden tests or stack traces. A matching request_id appears in internal logs. Unexpected exceptions use INTERNAL_ERROR with a safe message.

| HTTP status | Meaning in this API |
|---|---|
| 200 | Resource read or command completed |
| 201 | Resource created; Location returned |
| 202 | Submission durably accepted, evaluation still pending |
| 204 | Successful delete of an eligible draft/edge; no response body |
| 400 | Malformed JSON or invalid cursor |
| 401 | Missing, invalid or expired identity |
| 403 | Role or CSRF/origin denial |
| 404 | Missing or inaccessible resource; also not-yet-implemented route |
| 409 | State/revision conflict, graph cycle or incompatible duplicate command |
| 413 | Body/code exceeds enforced limits |
| 415 | Unsupported request content type |
| 422 | Well-formed input violates schema constraints |
| 429 | Enforced request/job rate limit; Retry-After supplied |
| 500 | Unexpected application defect |
| 503 | Temporary dependency or queue unavailability |

A correct solution and an incorrect solution both return a successful HTTP read of an evaluation resource. Do not use HTTP 500 for learner SyntaxError or a failed test.

## 7 Endpoint inventory and implementation stage

All paths below are relative to /api/v1 unless marked otherwise. The inventory is a plan; release routes only when tested. Do not implement placeholder routes that return fictional success.

| Stage | Method and path | Purpose |
|---|---|---|
| B0 | GET /health/live outside prefix | Process liveness |
| B0 | GET /health/ready outside prefix | Required service readiness; DB check once DB integration exists |
| B0 | GET /config/public | Supported modes, bounds and released feature capabilities |
| B1 | GET /me; PATCH /me; PATCH /me/settings | Current identity and permitted preferences |
| B1 | GET /skills; GET /skills/{skill_id} | Published skill inventory |
| B1 | GET /questions; GET /questions/{question_id} | Published question catalog and current public version |
| B1 | GET /question-versions/{version_id} | Exact allowed published public question version |
| B1 | POST /admin/skills; PATCH /admin/skills/{skill_id} | Create and edit skill with revision |
| B1 | POST /admin/questions | Create a question identity and first draft |
| B1 | POST /admin/questions/{question_id}/versions | Create next draft version |
| B1 | GET /admin/question-versions/{version_id} | Authorized full authoring preview |
| B1 | PATCH /admin/question-versions/{version_id} | Edit draft with revision; published data immutable |
| B1 | POST /admin/question-versions/{version_id}/publish | Validate and publish complete version |
| B1 | DELETE /admin/question-versions/{version_id} | Delete only unreferenced unpublished draft |
| B1 | POST /admin/questions/{question_id}/archive | Stop new attempts; preserve historical access |
| B2 | GET /skills/graph?curriculum_id={id} | Nodes, prerequisite edges and graph revision |
| B2 | POST /admin/skills/{dependent_id}/prerequisites | Add incoming edge from supplied prerequisite ID |
| B2 | DELETE /admin/skills/{dependent_id}/prerequisites/{prerequisite_id} | Remove incoming edge through graph service |
| B3 | POST /attempts; GET /attempts; GET /attempts/{attempt_id} | Start, list or resume an owned attempt |
| B3 | PUT /attempts/{attempt_id}/draft | Save complete current code draft with code revision |
| B3 | POST /attempts/{attempt_id}/pause or /resume | Confirm active-time transition |
| B3 | POST /attempts/{attempt_id}/extend | Increase permitted budget before expiry |
| B3 | POST /attempts/{attempt_id}/defer | Record incomplete work without false failure |
| B3 | POST /attempts/{attempt_id}/assistance/next | Disclose next hint/step and record delivery |
| B3 | POST /attempts/{attempt_id}/assistance/solution | Explicit full solution disclosure |
| B4 | POST /attempts/{attempt_id}/submissions | Store immutable source and create evaluation job |
| B4 | GET /submissions/{submission_id} | Poll public run/assessment evaluation status |
| B5 | GET /progress; GET /progress/skills/{skill_id} | Evidence and unmet mastery criteria |
| B5 | GET /reviews; GET /recommendations | Due practice and explainable next choices |
| B6 | GET /progress/skills/{skill_id}/statistics | Eligible counts, posterior and uncertainty by stratum |

Automatic expiry can call /assistance/next with trigger=budget_expired. The server verifies the phase actually expired; a client cannot falsely claim expiry to bypass step intervals. Early requested help uses trigger=learner_request and changes evidence eligibility normally.

Archive stops new attempts; an existing owner can still retrieve their pinned public version. A generic learner version lookup permits published, nonarchived content, plus historically archived versions only through verified owned-attempt access. Draft/private content remains admin-only. Add skill archival through a validated admin command when needed; ordinary DELETE must not erase evidence-linked skill records.

## 8 Exact input and output conventions

Reject unknown write fields. Omitted PATCH fields mean unchanged; explicit null is accepted only for a nullable field. Do not accept output-only fields such as user_id, assistance_level, mastery_level, elapsed_ms or status in learner command bodies. Server sets those values.

| Operation | Required input | Output highlights |
|---|---|---|
| PATCH /me | display_name when changing it | id, display_name, allowed preferences; no roles writable |
| PATCH /me/settings | Any selected timezone_name, default_practice_budget_seconds or hint_delivery_mode | Validated settings; timezone uses an IANA name |
| POST /attempts | question_version_id, mode, independent_budget_seconds | Attempt ID, question/policy version, lifecycle, timer and revision |
| PUT draft | source_code, expected_code_revision | New code_revision and updated_at; stale write is 409 |
| Pause/resume/defer | expected_revision; defer optionally reason | Current attempt snapshot and revision |
| Extend | expected_revision, additional_budget_seconds, optional reason | New budget and revision; cannot erase assistance |
| Assistance next | expected_revision, trigger | Only disclosed step, assistance level and next phase |
| Assistance solution | expected_revision, confirmation=true | Full solution/explanation, with permanent recorded exposure |
| Submit | source_code, purpose, expected_revision | Submission ID, pending status, accepted_at and poll URL |
| Admin prerequisite create | prerequisite_skill_id, expected_graph_revision | Edge and committed graph_revision |
| Admin write | Resource-specific content and expected_revision for edits | Validated draft or published resource |

Modes: practice, assessment, transfer and delayed_review. Purpose: public_run or assessment. Question versions declare supported modes; transfer/review attempts may additionally link their source recommendation/review ID, which must be owned and compatible. If a capability is not released, /config/public omits it and commands cannot use it.

Positive timer budgets must fit the pinned learning policy. A proposed practice range is 60–3600 seconds and extension cap is 1800 seconds per attempt, subject to the policy. Do not scatter these values across routers. Code strings are checked by UTF-8 byte length, not merely character count. Empty draft is permitted; empty assessment source is rejected. Names, allowed filters, curriculum IDs and enum values have explicit schemas.

### Content schemas before publication

POST /admin/skills accepts curriculum_id, code, title and competency. POST /admin/questions accepts code, family_id and a draft object. Creating a later version accepts the draft object alone; the server assigns version_number. Draft PATCH accepts only editable fields plus expected_revision.

The draft schema contains title, statement, track, difficulty, assessment_role, supported_modes, suggested_budget_seconds, contract, skill_mappings, pattern_ids, examples, test_cases, assistance_steps, solution and revision_links. Contract contains function_name, typed argument specifications, output specification, constraints and invalid_input_policy. Each skill mapping has skill_id, attribution_role and rubric. Examples have position, input, expected_output and explanation. Test cases additionally have visibility, assertion_rule and critical. Steps contain position, kind, content and next_budget_seconds. Solution contains reference_code, explanation and expected_complexity. Revision links contain target_version_id and link_type. IDs, positions, input/output representation and visibility are schema-validated; no arbitrary executable test expression arrives from a learner.

The B1 schema must explicitly add version title, supported_modes and draft revision fields to the abbreviated table inventory in the backend plan. Use assessment_role consistently for the question’s pedagogical role; it is distinct from user authorization roles. These are deliberate contract refinements to apply in the migration and ORM, not fields assumed to exist already.

Publication requires one primary assessed skill for the pilot, coherent supported modes, complete assistance/solution assets, executable reference-test verification and valid links. The public QuestionVersionResponse includes id, question_id, code, version_number, title, statement, track, difficulty, supported_modes, suggested_budget_seconds, public contract, skill IDs, pattern IDs and public examples. It excludes test_cases, assistance_steps, solution and internal rubrics. Admin preview uses a separate response schema.

Register static routes such as /skills/graph before dynamic /skills/{skill_id}, and test that graph requests cannot be swallowed by UUID parameter parsing.

### Starting an attempt

```http
POST /api/v1/attempts
Content-Type: application/json
Idempotency-Key: start-20261009-001
```

```json
{
  "question_version_id": "da417866-9fe0-4c66-a37f-9269a76a6a3b",
  "mode": "practice",
  "independent_budget_seconds": 720
}
```

Illustrative 201 response; UUIDs here are examples, not existing data:

```json
{
  "id": "fd0682d3-621f-4cca-a244-3161c15383cf",
  "question_version_id": "da417866-9fe0-4c66-a37f-9269a76a6a3b",
  "policy_version": "pilot-1",
  "mode": "practice",
  "lifecycle_state": "active",
  "assistance_level": "none",
  "revision": 1,
  "timer": {
    "phase_number": 0,
    "budget_seconds": 720,
    "active_elapsed_ms": 0,
    "remaining_ms": 720000,
    "server_now": "2026-10-09T04:00:00Z",
    "running_since": "2026-10-09T04:00:00Z",
    "expired_at": null
  }
}
```

Use this same AttemptSnapshot schema for GET and successful transition commands. Additional help responses nest it under attempt and include delivered_step. Initial phase numbering starts at 0 and subsequent help phases increment it. This specifies the previously unspecified numbering convention.

### Submission and asynchronous result

```json
{
  "source_code": "def first_unique(text):\n    return None\n",
  "purpose": "assessment",
  "expected_revision": 1
}
```

POST returns 202 only after the snapshot and job commit, including a new attempt_revision. It does not claim success or mastery:

```json
{
  "id": "567d3208-d1fd-4a46-8b9e-d83c27d39f5d",
  "status": "pending",
  "purpose": "assessment",
  "attempt_revision": 2,
  "accepted_at": "2026-10-09T04:01:00Z",
  "poll_url": "/api/v1/submissions/567d3208-d1fd-4a46-8b9e-d83c27d39f5d"
}
```

A later GET returns 200 and status pending, running, passed, failed or infrastructure_error. Pending evaluation has feedback=null. Completed feedback includes category, safe explanation, public test details and a bounded hidden-test summary. It does not return hidden inputs/expected outputs, reference code or raw learner-controlled traceback. Source retrieval is an explicit owner-only field or draft endpoint; do not send it in every list response.

Public runs evaluate public examples and do not create new assessment observations. They are disabled during an in-flight assessment and do not supersede immutable assessment code. An assessment pass grants evidence only after eligibility rules are applied. If no secure evaluator is available, reject new submissions with 503 EVALUATION_UNAVAILABLE; never return invented pass results.

## 9 Concurrency and retry contract

Required Idempotency-Key scope: authenticated principal, HTTP method, canonical path and key. Compare a validated canonical request body hash. A duplicate identical successful command returns its original status/body and Idempotency-Replayed=true; a conflicting payload returns 409 IDEMPOTENCY_CONFLICT.

Retain successful command records for at least seven days in the pilot. After expiry, the same key can create new work; clients must not retry old commands indefinitely. Durable uniqueness constraints still protect assistance steps, assessment observations and job result application. Concurrent identical requests return the first committed result or 409 COMMAND_IN_PROGRESS with a retry instruction. A rollback does not leave a falsely successful record.

Check authentication and ownership before replay. Idempotency lookup for an already committed command precedes revision validation; otherwise a successful replay would falsely fail because the original command changed the revision. Transient infrastructure errors are not cached as command success. A timeout is ambiguous: retry the identical request and key, never issue a new key merely because a response was lost.

Expected revisions are application fields, not HTTP If-Match in this first version. Therefore stale state is 409. If ETag/If-Match is adopted later, document its separate 412 Precondition Failed behavior. Do not implement a mixture implicitly.

Draft PUT is a complete replacement of the draft source with expected_code_revision. If the response is lost, read the current draft to reconcile revision/content before retrying. It uses optimistic conflict detection rather than POST-command idempotency. Preserve newer code if two tabs save out of order.

While an assessment evaluation is pending, assistance and another assessment submission return 409 EVALUATION_PENDING. Draft editing may continue, but cannot alter the submitted snapshot. Countdown continues; completing a pre-hint accepted solution is judged against its saved assistance context. Pending commands cannot disclose answers early.

GET is read-only from the client's perspective: it may calculate current remaining time, but cannot reveal new help, finish an assessment or award evidence. Poll submission status at approximately 1, 2 and then 5-second intervals while visible; back off on transient errors and stop on a terminal status. Attempt timer animation is local between server synchronizations, not a GET every second.

## 10 Pagination filters and freshness

List response:

```json
{
  "items": [],
  "next_cursor": null
}
```

Default limit is 20; maximum 100. Attempts use descending (created_at, id); skill/question catalogs use a defined stable ordering. Cursor is opaque, validated and bound to its filters and sort order. Unknown filters return 422. Malformed, expired or incompatible cursors return 400 INVALID_CURSOR. Enforce ownership again on every page.

Question filters initially include skill_id, difficulty, track and curriculum_id. Attempts may filter mode and lifecycle_state. Reviews may filter due_before and status. No arbitrary SQL field names or unrestricted user-provided sorting. Client cannot supply an owner filter to access another account.

Use Cache-Control: no-store on personalized responses, help, drafts, results, private authoring and errors. Defer public catalog caching until revision-aware invalidation is implemented. A progress response includes computed_at, policy_version and projection_status=current or rebuilding; avoid silently presenting stale recalculations as current.

Statistics return strata, eligible success/failure counts, prior parameters, posterior mean, uncertainty interval and exclusions. Sparse evidence is labelled limited. No endpoint promises an absolute Python mastery percentage.

## 11 API documentation and contract tests

In development, provide /docs, /redoc and /openapi.json when enabled. Generate schemas from typed FastAPI/Pydantic models once implemented. Keep stable operation IDs such as start_attempt, save_attempt_draft and reveal_next_assistance. Include examples, security requirements and documented error models for each released route.

The present document is a design specification, not a generated OpenAPI file. Before frontend integration, export the actual OpenAPI schema and test that implemented paths, inputs and outputs match this contract. Version the schema with the code; do not maintain a contradictory handwritten schema alongside it.

Required API tests include:

- Missing identity, cross-user UUIDs, revoked sessions, absent admin role and local-auth startup guards.
- Forbidden unknown fields, malformed JSON, invalid UUIDs, UTF-8 code-size boundary and oversized body.
- Every write's normal case, state conflict, stale revision and idempotent replay where applicable.
- A repeated committed command with its old revision replays correctly; a changed payload does not.
- GET never delivers new hints or records independent successes.
- Concurrent tabs cannot overwrite newer drafts; pending assessments do not accept help.
- Cursor boundaries, filter mismatch, max-page-size enforcement and owner isolation across pages.
- Public question/results exclude private tests, solutions and leaked validation inputs.
- CORS preflight, allowed origins, required headers and CSRF behavior for the deployed auth mode.
- Evaluation failures remain resource feedback; job outages become safe infrastructure results/errors.
- Request IDs appear in response/logs, and error payloads are safe and schema-compliant.

Run timing and business-policy tests separately from these API boundary tests. Use real PostgreSQL for locking/transaction integration tests. Tests for not-yet-built routes are not reported as passing placeholders.

## 12 Abuse limits and deployment requirements

Set body, code, output and queued-work limits before enabling evaluation. Proposed pilot quotas are 30 public runs and 10 assessment submissions per minute per authenticated principal, and one pending assessment per attempt. These need a shared limiter or DB-backed enforcement before hosting. A process-local counter cannot enforce a multi-worker limit. Admission refusal before durable acceptance uses 429 or 503; accepted jobs remain retrievable.

Question schema publication must check public/private separation and valid supported modes. Evaluation output needs runner resource limits and response truncation without leaking hidden fixtures. TLS, trusted proxies, rate limits, session lifecycle, backups and restore verification are deployment requirements. They do not block local app bootstrapping.

## 13 What still remains before and during coding

| Item | Status | When it matters |
|---|---|---|
| Stack, layers, IDs, storage and transaction ownership | Designed in backend contract | Ready for implementation |
| REST conventions and environment settings | Specified here | Implement and verify in each increment |
| Runtime/dependency setup and actual versions | Not executed | B0 first task using uv on Linux/WSL |
| First migration and constraints | Designed, not implemented | B1 with PostgreSQL integration tests |
| Initial branch question pack | Inventory exists; full tests/hints/variants still needed | Before the learning-loop pilot |
| Content JSON schema and import command | Still to implement and validate | B1 publication workflow |
| Runner protocol and secure isolation technology | Not selected or verified | Before B4 real execution |
| Login provider and deployed session integration | Not selected | Before hosting or multiple users |
| Hosting, TLS, origins and proxy configuration | Not selected | Deployment increment |
| Generated OpenAPI schema | Depends on actual API code | Export after each released API increment |
| CI pipeline and migration checks | Requirements known; files still needed | Start quality checks in B0, integration checks in B1 |
| Backup/restore, retention and account erasure | Operational policy still needed | Before real hosted user data |
| Formula and recommendation calibration | Provisional defaults | After real attempts, not before app setup |

Nothing here requires us to design the entire platform before starting B0. We can implement environment setup, settings, app factory, logging, health and their tests now. Decisions are resolved immediately before the affected capability is built, with the contract updated when evidence changes a rule.

## 14 References and document precedence

HTTP semantics: https://www.rfc-editor.org/rfc/rfc9110.html

FastAPI CORS: https://fastapi.tiangolo.com/tutorial/cors/

FastAPI validated settings: https://fastapi.tiangolo.com/advanced/settings/

These sources explain HTTP and framework behavior. Specific limits, paths and payloads above are our proposed product decisions. They are not vendor recommendations.

Use the master blueprint for learning goals, the backend contract for architecture and data rules, this document for HTTP/settings details, and AGENTS.md for contributor behavior. Resolve conflicts explicitly in a decision record; implementation and its tests must not quietly invent a different contract.

## Released skill graph increment (9 October 2026)

The [skill graph decision](decisions/0004_skill_graph.md) specifies the implemented
B1 skill CRUD and B2 prerequisite storage subset. All routes use /api/v1:

| Route | Implemented contract |
|---|---|
| GET /skills | Stable (code, UUID) cursor pages; curriculum_id, include_archived, limit (20/default, 100/max), cursor |
| GET /skills/{skill_id} | Explicit skill identity, metadata, revision and archived_at; preserves archived detail |
| GET /skills/graph | Required curriculum_id; optional center_skill_id, direction=both/prerequisites/dependents, depth=1..5; max_nodes=100 (max 100), max_edges=200 (max 500) |
| POST /admin/skills | curriculum_id, code, title, competency; 201 and Location; stored admin and Idempotency-Key |
| PATCH /admin/skills/{skill_id} | expected_revision and title and/or competency; stable code/curriculum; 200 |
| POST /admin/skills/{skill_id}/archive | expected_revision, expected_graph_revision; Idempotency-Key; 200 |
| POST /admin/skills/{dependent_id}/prerequisites | prerequisite_skill_id, expected_graph_revision; Idempotency-Key; 201 with canonical edge Location |
| PUT /admin/skills/{dependent_id}/prerequisites | prerequisite_skill_ids (unique, max 100), expected_graph_revision; atomic full incoming-set replacement; 200 |
| DELETE /admin/skills/{dependent_id}/prerequisites/{prerequisite_id} | expected_graph_revision query; 204; reload graph for committed revision |

Edges always point prerequisite -> dependent. Graph reads return curriculum_id,
graph_revision, nodes and edges. Neighborhoods are induced subgraphs of nodes
reachable within the chosen direction/depth. Bounds are checked without silent
truncation: 422 GRAPH_READ_LIMIT requests a narrower neighborhood or larger bounds.
Unknown fields/filters are 422. A graph snapshot uses a short shared curriculum
lock; graph mutations use its exclusive row lock and validate in that transaction.
Add/remove/replacement require the current graph revision. Conflicts use 409
STALE_REVISION, GRAPH_CYCLE (skill-code path), SELF_PREREQUISITE, DUPLICATE_EDGE,
SKILL_ARCHIVED or SKILL_IN_USE. Missing dependent/curriculum is 404; invalid,
archived or cross-curriculum prerequisite is 422 INVALID_SKILL.

Remove incident edges before archival. Resolve mappings on available questions by
editing drafts or archiving their questions. Mappings on archived questions are
retained, including immutable published assets. Archived skills cannot accept
edits/edges and are omitted from active graph/default catalogs. All mutations use
the existing database-resolved admin policy; missing identity configuration denies
writes and local identity remains disabled in production. Prerequisites guide
future recommendations and never introduce learner access restrictions.

See [current generated OpenAPI](openapi.b2-skill-graph.json) and
[actual verification](B2_Verification.md). Previous OpenAPI files remain historical
release snapshots. No recommendations, mastery, timers, submissions or execution
are implemented; trusted production publication remains unavailable.
