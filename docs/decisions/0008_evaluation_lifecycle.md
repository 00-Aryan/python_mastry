# B6a evaluation lifecycle and runner boundary

Rules recorded before coding, 10 October 2026. This increment implements orchestration,
not execution. B5 source receipts stay immutable and never start jobs implicitly.

## Acceptance and ordering

POST /submissions/{id}/evaluations accepts expected_revision and Idempotency-Key.
The database learner owner of an active/paused attempt can request one job per
immutable submission, including after question archival. Submission purpose chooses
public-only tests for public_run or all published tests for assessment. Pin submission,
question, attempt learning policy, immutable test bundle and separate evaluator policy.
Bundle membership references existing immutable published tests; no duplicated answers.

User -> attempt -> job locks match existing mutation ordering. New requests check the
attempt revision, reconcile expiry, append evaluation_requested and advance revision.
Job, initial transition, indefinite request receipt and dispatch intent commit together.
Exact retries recover the original 202/Location before availability/lifecycle/revision
checks; changed payload conflicts. A distinct key for an already evaluated submission
returns EVALUATION_EXISTS. Internal infrastructure retries reuse the same job.

A pending/running assessment blocks new help (including solution escape), new assessment
receipts and new evaluation requests on that attempt with 409 EVALUATION_PENDING.
Already granted help/receipt retries and reads remain available. Public-run jobs do not
block help. Pause/resume/extend/defer/abandon remain available and countdown continues;
ending an attempt does not cancel committed jobs or change submission evidence. Results
never complete an attempt or produce independent eligibility, recommendations or mastery.
This resolves the old atomic submit+job plan: intake and evaluation are separate commands.

## States, deadlines and recovery

States: pending -> running -> passed/failed/infrastructure_error. Running may return
to pending only for retryable infrastructure faults. Terminal states have no outgoing
transitions. Each transition is append-only, sequenced per job with server UTC time.
There are at most three dispatch generations, 30-second leases, 5/10-second backoff,
and a 300-second overall acceptance deadline. Lease and overall deadline equality
are expired. Timeout, dispatch failure, invalid result and exhausted recovery are
infrastructure errors, never incorrect code. Learner syntax/test/resource failures
are failed with distinct safe categories, only when reported by a supported runner.

The immutable dispatch-intent row plus pending job is the PostgreSQL outbox. A worker
claims one due job using FOR UPDATE SKIP LOCKED, commits generation/token/lease,
then calls the adapter outside a transaction. Results require the current generation,
opaque lease token, exact pins/hash, expected runner identity and protocol version.
Duplicates, expired leases and stale generations return ignored without overwriting
any result. Recovery requeues expired leases or finalizes deadline/exhaustion. A crash
before dispatch or after dispatch/before result commit therefore permits bounded
at-least-once redelivery. Adapter delivery must tolerate repeated job/generation IDs.
No worker daemon or scheduler is enabled here; explicit application worker methods
are exercised only with adapters defined under tests. Worker recovery handles delayed jobs. A new help/assessment command also finalizes
an overdue pending assessment under the same locks, preventing an indefinite help
lock when a worker stops. If that command fails, its transaction rolls recovery back;
independent worker recovery remains available. Status polls are read-only.

## Versioned runner boundary and authenticity

Protocol v1 request carries the originating request_id, job/generation/token, submission/source SHA-256, source,
question/learning-policy/test-bundle/evaluator-policy pins, bundle hash, function
contract, selected tests, runner identity and execution deadline. Strict result v1
contains the identical correlation envelope plus an allowlisted outcome; no raw
stdout, traceback, hidden-test diagnostics or freeform explanation is accepted.
The adapter owns transport authentication and response verification. Correlation IDs
and identity strings alone are not authentication. There is no HTTP result callback.

Default API/worker binding is unavailable, returning 503 EVALUATION_UNAVAILABLE
without changing state. This release accepts adapter injection only in APP_ENV=test;
there is no supported real adapter, RUNNER_URL switch or importable fake implementation.
Tests validate orchestration, not source correctness or future transport authenticity.
Before a real binding is registered it must verify mutually authenticated transport,
allowlisted runner/service identity and signed/authenticated result envelopes (including
all pins, lease token and nonce), bounded responses, replay resistance and secret rotation.
Untrusted learner output cannot be parsed as a trusted result envelope.

## Execution release gates

A future runner must isolate unprivileged learner code from API/database credentials,
network, host filesystem, other runs and private harness/expected outputs. Enforce CPU,
wall time, memory/process/file/output bounds, controlled mounts, read-only artifacts,
cleanup, deterministic Python/evaluator image identity and comparison outside learner
context. Verify introspection, resource exhaustion, file/network escape, forged-result
and cross-job attacks. A subprocess timeout or restricted builtins is insufficient.
Until those gates and production authentication are verified, production evaluation
and publication verification remain unavailable. This increment executes no source.

## Persistence, privacy and verification

Normalized immutable bundles/memberships, evaluator policies, dispatch intents,
request receipts and job transitions accompany mutable current job projections.
PostgreSQL protects pins, terminal results and transition legality; restrictive FKs,
unique submission/job and request keys, lease/state constraints back application rules.
Downgrade refuses evaluation history. Job detail returns safe state and bounded
transitions only; owner attempt history uses limit 20/max min(100, MAX_PAGE_SIZE),
context-bound one-day high-water cursors. No source, test membership/input/output,
lease token, runner credentials or raw diagnostics enters public responses or logs.

Domain defines transition/result schemas and categories; repositories load owned
history/bundles and claim without commits; services own admission/result/recovery
transactions; worker owns the adapter call outside transactions; thin routes translate
HTTP. Acceptance tests cover authorization/pins/retries/concurrent admission, pending
assistance ordering, stale/duplicate/terminal results, deadlines/recovery/dispatch faults,
rollback, DB guards, bounded privacy and real B5 migration/data preservation. Run the
full suite, Ruff, strict mypy and source/wheel checks, recording actual limits.

The concrete JSON schemas are exported in [runner protocol v1](../runner-protocol.v1.json).
Dispatch intent preserves request_id; worker logs/adapter requests reuse it.
