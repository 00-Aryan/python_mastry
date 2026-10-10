# B6a evaluation lifecycle verification

Verified locally, 10 October 2026, on Linux with Python 3.12.14, uv 0.12.23 and
PostgreSQL 18.6. Rules were documented before coding in
[decision 0008](decisions/0008_evaluation_lifecycle.md). The
[B6a API contract](REST_API_Settings_and_Contract.md#released-b6a-evaluation-lifecycle-10-october-2026),
[OpenAPI snapshot](openapi.b6a-evaluation-lifecycle.json) and
[runner protocol v1 schemas](runner-protocol.v1.json) describe the implemented boundary.

## Baseline and actual checks

The clean B5 commit eb015cd passed all **244** PostgreSQL/regression tests before
changes, plus uv sync --locked, Ruff and strict mypy. Existing ownership, immutable
question/submission/assistance storage, revision/expiry ordering, short transactions
and durable retries were inspected and reused. The disposable PostgreSQL installation
had disappeared from /tmp; Ubuntu packages were downloaded/unpacked there and a fresh
local test cluster created without installing system packages. No dependencies or
credentials were added to the repository; pyproject.toml/uv.lock/.python-version agree.

| Check | Actual result |
|---|---|
| `uv sync --locked` | Passed |
| `TEST_DATABASE_URL=… uv run pytest -q -W error --cov=mastery_backend --cov-report=term-missing` | **303 passed**, **98% statement coverage**, no skips/warnings; final run 64.28 seconds |
| New B6a checks | **44** real PostgreSQL integration cases and **15** pure policy/transition cases passed |
| `uv run ruff check .` | Passed |
| `uv run ruff format --check .` | Passed, 122 files |
| Strict `uv run mypy src migrations` | Passed, 82 source files |
| Normal Alembic CLI | Upgraded disposable public schema to B5, then B6a; current head **0007_evaluation_lifecycle** |
| `uv run alembic check` | No new upgrade operations detected |
| Migration/data test | Existing B5 source/evidence survived real downgrade-to-B5/upgrade unchanged; schema matched metadata; downgrade with evaluation history refused with 23514 and retained head/data |
| Build | Source and wheel built; initial offline attempt lacked cached uv_build, declared backend fetched, subsequent `uv build --offline` passed |
| Package inspection | Source includes migration, decision, runner schemas, OpenAPI, verification, Alembic config, lockfile, AGENTS and Python version; wheel includes orchestration/interface modules and no test adapters/verifier/tests/.env/virtual environments |
| Installed wheel smoke | Imported from temporary wheel target using project dependencies; default runner unavailable; policy validation and exact 35-path/40-operation schema passed |
| Generated schema | 35 paths, 40 distinct operation IDs; typed status/history and safe errors, no result callback |
| Diff review | Reviewed API privacy, pinning, locks, deadlines, transactional adapter boundary, replay, migration guards and package contents; diff checks passed |

Tests used isolated random schemas in the disposable mastery_test database,
independent sessions and deterministic clocks. PostgreSQL/TestClient checks required
sandbox escalation. No SQLite stand-in or learner-code execution was used.

## Acceptance evidence

| Requirement | What passed |
|---|---|
| Admission/ownership | Fresh database learner role required; another learner or admin received 404; revoked role 403; missing identity 401. Invalid owner/pins/status/source fields and nonpositive revisions rejected safely. Deferred/abandoned attempts denied admission; existing owned archived content allowed |
| Availability boundary | Default request returned 503 EVALUATION_UNAVAILABLE without job, intent, revision or expiry mutation. Injected adapter denied in development/production; no fake implementation shipped in package |
| Pins/assets | Submission/question/learning-policy/test-bundle/evaluator-policy pins persisted; future published question/policy did not alter jobs. Public-run bundle contained only public tests; assessment bundle contained public/private tests. Bundles reference existing immutable test rows |
| Atomicity/replay | Job, initial transition, dispatch intent, attempt event/revision and permanent receipt committed together. Exact keys returned original 202/detail/Location, including after terminal attempt, disabled adapter and nine-day delay; changed revision conflicted. Distinct keys for one submission returned EVALUATION_EXISTS |
| Concurrent admission | Parallel identical keys created one job/intent/event and one replay. Parallel distinct keys produced one job and one conflict. Help vs admission at one revision produced one success/one stale conflict; refreshed help obeyed pending lock, saved receipt evidence stayed unchanged |
| Pending assessment | New help/solution escape, assessment source intake and public-run evaluation requests blocked; saved source reads/retries remained available. Public source receipts and pause/end remained available; ending an attempt did not cancel its job or invent completion |
| Leases/results | SKIP LOCKED allowed at most one concurrent claim. Results checked all pins/hashes/identity/token/generation. Concurrent different outcomes committed at most one terminal result; duplicate, stale, forged-correlation and expired results could not overwrite final state |
| Boundaries/recovery | 29,999 ms result accepted; 30,000/30,001 ms expired and old result ignored. Recovery requeued with new generation/token after backoff; service recreation recovered abandoned leases. Overall deadline and help admission tested at 299,999/300,000/300,001 ms. Valid help finalized overdue assessment without a worker; failed help rolled recovery back |
| Infrastructure distinction | Dispatch exceptions, timeout exceptions, malformed/forged/late results and infrastructure outcomes retried or ended as infrastructure_error. Three generations and 5/10-second backoff bounded retries. Synthetic incorrect/syntax/resource outcomes became failed; none changed mastery, independent eligibility or attempt lifecycle |
| Transaction boundary | Another connection acquired the job row lock during adapter dispatch, proving the claim transaction had ended. Admission/result post-flush faults rolled back history/projections and successful retries recovered. Backward evaluation clock rejected without a terminal write |
| Immutable history | PostgreSQL rejected job pin/terminal updates/deletion and modifications/deletion of events, policies, bundles/memberships, dispatch intents and retry receipts with 23514. Deferred guards require matching transition history and dispatch intent |
| Read consistency/history | Detail held the job projection lock through transition SELECT; concurrent claim skipped it. Bounded metadata pages used acceptance event sequence, preserving equal-time order, excluding later jobs and binding expiring cursors to owner/attempt. Invalid cursors/limits and MAX_PAGE_SIZE rejected |
| Privacy/tracing | Status/history/errors excluded source, hidden fixtures/expected outputs, hints/solutions, raw diagnostics and tokens. Result schema rejected stdout/diagnostics and unsupported versions/outcomes. Safe logs used opaque job ID; durable request_id propagated into adapter/worker context; existing public privacy regressions passed |
| Regressions | All B0–B5 identity/settings/middleware/content/graph/timer/assistance/submission tests passed |

Intermediate runs found a migration CASE-expression syntax error, test import/fault
injection issues and the stale B5 route inventory; these were corrected. Review added
transactional deadline admission recovery and a status/history lock consistency test.
The final complete suite was rerun after those changes; earlier failed runs do not
count as successful checks.

## Responsibilities and resolved contract gaps

Domain evaluations.py owns typed protocol/status values, policy bounds and transition
legality. EvaluationRepository selects owned history, immutable bundle memberships and
due work; it never commits. EvaluationService owns admission and reads; shared
application evaluation_transactions owns transition/deadline rules used by assistance,
submission and worker paths. EvaluationWorker owns claim/result/recovery transactions
and invokes RunnerAdapter after claim commit. Thin evaluation routes translate HTTP.
Migration 0007 adds normalized pins, immutable facts, mutable job projections and guards.

The original combined submission/job proposal is refined into two commands: B5 receipt
intake and B6a evaluation admission. Receipt received/not_requested remains a historical
fact; polling the evaluation gives current state. New requests use expected_revision
and one job per submission; infrastructure retries reuse that job, with no learner
manual requeue endpoint. Assessment pending locks become real only when jobs exist.
Expiry grants no automatic help or correctness, and results never end attempts or
compute evidence. Defer/abandon does not cancel committed work. Owner history stays
readable after archival/end. Existing successful retries precede new-admission rules.

At deadline equality an overdue assessment can be finalized by worker recovery or a
valid new help/assessment command, avoiding an indefinite help lock after worker loss.
Failed commands roll that recovery back; independent recovery remains available.
Read-only status/history do not sample the solving clock or perform recovery. No daemon,
scheduler or production runner registration is included. The immutable intent plus
pending job forms the durable PostgreSQL outbox; no network action occurs at admission.

## Explicitly unverified limits

No learner code was executed. Synthetic adapter envelopes verify orchestration and
privacy only; they prove neither source correctness nor a future runner's isolation,
transport authentication or result authenticity. A runner identity string and lease
nonce alone are not cryptographic authentication. A future adapter must authenticate
transport/results, enforce deadlines/resource/output bounds, pin image/runtime and
pass adversarial isolation/private-harness tests before registration. Those guarantees
remain **unimplemented and unverified**. There is no unrestricted result callback.

Production admission remains 503 until a supported real runner is implemented.
Production publication still awaits the trusted reference verifier; controlled
published fixtures prove transition logic only. Deployed authentication remains
unreleased and production startup disabled. No execution, grader, publication verifier,
recommendations, mastery/checkpoint calculations or independent-success claims were added.

Real process/host crash injection, actual lost socket responses, remote CI, Docker/fresh
WSL setup, distributed clock drift, production load/quotas and a running worker daemon
were not checked. Crash/lost-response windows were modeled using abandoned leases,
ignored successful responses, rollback injection and worker/service recreation. Timeout
exceptions/deadline checks are deterministic orchestration tests, not measured wall-clock
cancellation of a real executor. Wheel smoke used project dependencies rather than a
fresh online dependency installation.

The configured Git author is reused unchanged. .env, credentials, caches, virtual
environments, database artifacts and build output remain ignored.
