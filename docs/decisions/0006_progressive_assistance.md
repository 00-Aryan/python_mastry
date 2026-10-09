# B4 progressive assistance

Written before implementation, 2026-10-10. This user-requested B4 is assistance,
not the execution milestone numbered B4 in the original broad roadmap.

## Transitions and gaps resolved

Only an active or paused owned attempt may receive assistance. The API/domain
names remain directional -> pattern -> pseudocode -> partial_code (logical code
steps) -> full_solution. Existing published versions may omit intermediate kinds;
follow their immutable ordered assets without inventing missing content. Ordinary
next never grants the final full_solution: when it is next, return
ASSISTANCE_EXHAUSTED with instructions to use the confirmed solution escape.

The first directional/available non-solution step may be requested early with
trigger=learner_request. trigger=budget_expired requires actual phase expiry.
After a grant, both triggers require the current waiting phase to expire. The
step's published next_budget_seconds starts the next phase at the grant time;
o pre-grant overdue time counts toward it. Policy bounds are 60..86400 seconds.
Boundary equality permits advancement. Missing/invalid pinned assets return safe
503 ASSISTANCE_UNAVAILABLE and roll back the command, including expiry reconciliation.

Pause freezes active waiting time; resume restarts it. Offline/reload/restart do
not pause. Extend works only before expiry using the existing pinned extension
bounds and total phase budget bounds; it never erases a grant. Defer/abandon are
terminal and deny new grants. Successful grant retries remain available after
terminal transitions to recover a lost response, provided current ownership and
learner authorization still hold. Full-solution escape requires confirmation=true
and works immediately from active/paused, regardless of waiting interval or ladder
position. It grants only the terminal step plus the pinned reference solution and
explanation. It closes the current phase without ending the learning session;
further next/solution requests with new keys return ASSISTANCE_EXHAUSTED. It never
claims correctness or that the learner read the response.

The independent interval ends permanently on expiry or first early grant (reason
assistance_requested); its original closure is retained through later phases.
Grant history and assistance_level can only move forward. Timer snapshots show the
latest phase; full solution freezes its unused remaining duration. Overdue duration
is total active solving time minus accumulated elapsed time in all phases, not
minus only the latest phase. No countdown tick writes are introduced.

New attempts pin pilot-assistance-1, including timer and assistance bounds. The
immutable B3 pilot-timer-1 policy has no assistance configuration: existing attempts
retain timer behavior and return 503 POLICY_UNAVAILABLE for new assistance. This
avoids retroactively changing a pinned policy. Archival still prevents new starts;
existing owners can use their published pinned assets, including archived versions.

## Transactions, retries and privacy

Follow the established user -> owned attempt row lock order. Reconcile server time,
check expected_revision and lifecycle, validate pinned policy/asset, close the old
phase, insert a grant/new phase/event and increment the revision in one transaction.
Concurrent distinct requests with the same revision: one success, one stale conflict;
a fresh revision still cannot bypass the waiting interval. Each grant stores a
per-attempt operation/key and canonical request hash plus the original response
snapshot. Identical retries return that response indefinitely without a clock read,
phase reset or extra grant; incompatible reuse returns IDEMPOTENCY_CONFLICT. Grants
are append-only and their assets must belong to the attempt's published version.

Only owned assistance commands/history load granted private assets. Generic public
question endpoints, attempt detail/list/question, errors and logs contain no hint
or solution text or private tests. History reads return granted stages only, bounded
by the published five-stage ladder. No endpoint reports a visually read timestamp.

## Responsibilities and acceptance

Domain assistance rules enforce first-help/wait/escape semantics; the existing timer
projection remains the clock authority. AssistanceService owns short transactions
and composes AttemptService clock reconciliation. AssistanceRepository reads only
the pinned next/terminal asset and persists grant facts without commits. Thin routes
validate request fields and return explicit response models. Migration 0005 extends
phase/event constraints and adds immutable grant storage and the new policy.

Tests cover before/equal/after release boundaries; pause/resume/extend and irreversible
closure; unauthorized/terminal attempts; exact duplicate and opposing requests;
rollback/lost responses; missing assets/exhaustion; full solution; pinned archived
content; PostgreSQL upgrade/constraints/history protection; and no public/error
leakage. Run all regressions, Ruff, strict mypy and package checks. Publication still
requires a future trusted verifier; controlled verifiers stay in tests only.
