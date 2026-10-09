# B3 attempt lifecycle and server timers

Date: 9 October 2026. Written before implementation.

This increment stores owned attempts, their initial independent phase, immutable
timer policy, ordered lifecycle events and family exposure at start. It releases
start/list/detail, pause/resume, bounded extension and unresolved end/abandon. It
adds no hint delivery, draft code/submissions, execution or learning calculations.

## State transitions

| Command | From | To / effect |
|---|---|---|
| Start | No attempt | active; independent phase 0 starts atomically with an event |
| Pause | active | paused; materialize active durations, clear running anchors |
| Resume | paused | active; set total running anchor; restart phase anchor only if not expired |
| Extend | active or paused, phase unexpired | Same lifecycle; increase budget within pinned policy, append amount/reason |
| Defer (end unresolved) | active or paused | deferred, terminal; materialize time and close interval without a correctness judgment |
| Abandon | active or paused | abandoned, terminal; same accounting, explicit voluntary stop |
| Expiry | active, budget exactly exhausted | Lifecycle stays active; independent phase closes; assistance becomes eligible |

The contract names unresolved ending `/defer`; use that route rather than inventing
an ambiguous success-producing `/end`. Add `/abandon` for the explicitly requested
voluntary stop. `completed` is reserved for a future validated evaluation, with no
manual completion endpoint. Deferred/abandoned attempts cannot resume or extend;
start a new attempt to work again. A different key repeating pause/resume or a
terminal action returns 409 INVALID_ATTEMPT_STATE. Identical successful POST
replays retain the original result, even if its expected revision is now stale.

## Timer policy and accounting

All instants are aware UTC, normalized down to milliseconds; budgets are integer
seconds and elapsed/remaining durations are integer milliseconds. A Clock is
injected; the runtime implementation reads server UTC. One timer timestamp is
sampled after transaction locks, never trusted from a browser. A backward clock
before the persisted last reconciliation/running anchor returns 503 CLOCK_UNAVAILABLE
without mutation. Clocks must be synchronized across deployed servers; no process
clock/cache is persistence authority.

The immutable migration-seeded policy `pilot-timer-1` permits practice and
assessment, selected budgets 60–3600 seconds, extensions 1–1800 seconds per command,
and a total phase budget of at most 3600 seconds. Requests reject booleans/fractional
values and unsupported modes. The question version must support the chosen mode.
Transfer/review context and policies are deferred. Every attempt pins this policy
and its published question version, so future settings/policies/content versions
cannot reinterpret elapsed time or budgets.

Running phase elapsed = min(budget_ms, stored phase elapsed + milliseconds since
phase running_since). Remaining = max(0, budget_ms - elapsed). Total active solving
time uses its own stored duration/running anchor and continues after expiry;
overdue time is total active time minus the capped independent-phase duration.
Pause freezes both; offline/browser closure does not pause either. Confirmed
pause takes effect only when received by the server. Assessment pause or extension
sets a permanent timing_accommodated flag; this does not award or compute credit.

At now == the budget boundary the phase expires. Its expired_at is the exact
boundary, not the later observation time. Phase elapsed freezes at budget and its
running anchor clears; total active solving can continue. Expiry permanently ends
the independent interval and makes assistance eligible, without revealing a hint,
judging an answer or terminating the session. Resume after expiry only resumes total
solving time. Extensions are allowed only before expiry, including while paused;
at/after expiry they return 409 PHASE_EXPIRED. They never clear expiry, independent
closure or assistance history. Assistance_level stays none in this increment.

Reads calculate live durations from stored anchors without per-tick writes. On
first observed expiry a locked read writes the expiry event/marker once and bumps
revision; subsequent reads project time without writes. Commands check the stored
expected_revision before reconciliation, then record expiry and the explicit
transition atomically. If expiry is first observed during a valid command it adds
an expiry event/revision and then the command event/revision. Invalid commands roll
back reconciliation too; a later read records the historical boundary. GET does
not complete attempts, disclose assistance or create evidence.

## Ownership, pinning, retries and storage

The existing loopback development principal is resolved from active users and
stored roles. Learner routes require the stored learner role, rechecked in the
transaction. Ownership is in repository WHERE clauses; another user's UUID returns
404, not admin access. Missing identity configuration returns 401; role denial 403.
Production authentication remains disabled as before.

Transactions lock user then owned attempt; start additionally locks the question
against concurrent archival. Each operation owns its session. Start creates
attempt/phase/event and family-exposure record in one commit; the user lock ensures
concurrent starts cannot both claim first family exposure. The stored familiarity
flag is context only, not an evidence/mastery decision. Repositories never commit.
Published content/private asset guards remain unchanged. New starts on archived or
draft versions return 404. Existing attempts keep their exact version and can still
read its public projection through `/attempts/{id}/question` after archive. Generic
question detail continues to hide archived content; no private tests/hints/solutions
are returned. Existing owned attempts may continue or close after question archival.

Every state-changing POST uses the existing 1–128 printable-ASCII Idempotency-Key,
principal/method/path/body-hash scope and seven-day retention. Authentication and
resource ownership precede replay, and replay precedes revision validation. Failed
transactions create no success receipt. Replays include the original server_now;
clients GET current state after replay to resynchronize. Infrastructure receipt
retention uses wall UTC independently of the injected solving clock.

Attempts/phases have foreign keys, positive counters/nonnegative durations, state
checks, one open phase per attempt and unique phase numbers. Events are ordered,
append-only facts. PostgreSQL guards immutable policy configuration, attempt owner/
question/policy pinning, persistent interval closure, timing accommodation and
phase expiry against ordinary updates. No learner DELETE erases attempt history.
No attempt-draft table/route is added until code editing is in scope.

## API and acceptance plan

Release POST/GET /attempts, GET /attempts/{id}, GET /attempts/{id}/question and
POST /attempts/{id}/pause, /resume, /extend, /defer and /abandon. Start accepts
question_version_id, mode and independent_budget_seconds. Commands require
expected_revision; extension also accepts additional_budget_seconds and optional
reason, defer/abandon an optional reason. Snapshot includes server time, pinned IDs,
policy version, lifecycle/revision, assistance eligibility/level, permanent interval
closure, total/overdue durations, timing accommodation and phase clocks. List reads
are owned, cursor-paginated in descending (started_at, UUID), 20/default and 100/max.
A bounded list reconciles expiry using one timer timestamp under locks. Public
configuration advertises only attempt_lifecycle/server_timers and practice/assessment;
learning_policy remains null because no learning/evidence policy is released.
Health/config release_stage becomes B3-attempt-timers; evaluation stays not_integrated.

Acceptance tests will use controlled clocks and test-only verified published
fixtures. Cover exact boundaries, bounds/types, pause/resume/reloads/offline and
restart persistence, overdue time, clock rollback, extension/expiry permanence,
replay/conflicts/concurrent mutations, invalid/terminal states, ownership and
stored-role revocation, rollback, version/policy pinning/archived history and private
responses. Upgrade from real B2 PostgreSQL data, compare schema/metadata, verify
constraints/guards, run regressions/Ruff/strict mypy and source/wheel checks.
Production publication stays unavailable; test fixtures are not a bypass.

## Implemented file responsibilities

| File | Responsibility |
|---|---|
| api/routers/attempts.py; api/schemas/attempts.py | Typed HTTP inputs, ownership dependency and response translation |
| api/dependencies.py | Existing local principal guards, stored learner role and injected Clock/service |
| application/attempt_service.py | Start/read/list/transition transactions, expiry reconciliation and snapshots |
| application/clock.py | Clock protocol and runtime UTC adapter; no process-local countdown |
| application/command_replay.py | Existing durable replay/hash/receipt rules shared with admin commands |
| domain/timer_policy.py | Pure duration projection, bounds and lifecycle transition policy |
| domain/attempt_records.py | Explicit public timing snapshots and bounded list query |
| infrastructure/database/attempt_models.py | Normalized policy, attempt, phase, event and initial family exposure tables |
| infrastructure/database/attempt_repository.py | Ownership-filtered row locks, availability/reference queries and append-only events |
| infrastructure/database/catalog_repository.py | Shared public projection, with archived access only after owned-attempt lookup |
| migrations/versions/0004_attempt_timers.py | Static reviewed DDL, initial policy and immutable-history guards |

Lists batch phase/policy lookups; before expiry no INSERT/UPDATE/DELETE is issued.
Start and transitions log safe attempt ID, revision, policy and lifecycle context
after commit, with the existing request_id. Reasons and private question content
are not emitted in logs. Event sequence, phase and stored timer fields permit
reconstruction without duplicating per-tick events.

No code-draft or hint endpoint was added despite the broader planned B3 inventory.
No external execution or worker is needed for this timer slice. Migration downgrade
drops B3 attempts/history/policy and must only be used on disposable schemas; retain
real history with forward migrations. Actual checks are in docs/B3_Verification.md.
