# B5 owned immutable submissions

Rules documented before implementation, 10 October 2026. The current user calls
receipt storage B5; original execution/scoring backlog numbering remains future.

## Acceptance and lifecycle rules

POST /api/v1/attempts/{id}/submissions accepts source_code, purpose=public_run or
assessment, expected_revision and Idempotency-Key. Only the database learner owner
of an active or paused attempt can submit. Both purposes are stored intent, not an
execution action; both are permitted in released practice/assessment modes. Expired
and fully assisted active/paused attempts can submit. Deferred, abandoned and
completed attempts reject new intake. Historical detail/list and exact successful
retries remain readable after terminal transitions or question archival.

The receipt status is received and evaluation is not_requested. No job, pending
assessment, correctness, independent-success or mastery assertion is created.
The broader pending-assessment help lock applies only when future evaluation work
actually exists; it does not apply to a receipt. Multiple submissions are allowed,
including identical source under distinct keys, with distinct immutable UUIDs.

Preserve source exactly: UTF-8 bytes, whitespace and line endings are not rewritten.
Enforce configured MAX_CODE_BYTES (default 65536); existing HTTP body middleware
also enforces MAX_REQUEST_BODY_BYTES (default 262144). Code over the byte bound
returns 413 CODE_TOO_LARGE; malformed fields return 422. Blank/whitespace-only
source is rejected for both purposes (submissions are not drafts). Incorrect or
syntactically invalid nonblank Python is accepted unchanged without parsing,
compiling, importing or executing it. Reject U+0000 and invalid UTF-8 surrogate
strings with safe 422 INVALID_SOURCE, since PostgreSQL text cannot store them.
A submission claims Python source intake only, not verified language/syntax.

## Ordering and captured evidence

Use the established database user -> owned attempt lock order. Check durable retry
before revision/lifecycle/size checks, then validate a new request, sample the
injected UTC clock after locks, reconcile expiry, materialize timer anchors, append
submission_received and increment revision in the same transaction. Capture the
pinned question/policy IDs, acceptance UTC time, event sequence, mode, lifecycle,
assistance level, previously granted assistance IDs, current phase ID and the full
public timer/attempt snapshot (including independent closure, accommodation and
familiar-family context). This is input for future eligibility rules, not a computed
eligibility decision. Assistance text/private tests/solutions are never loaded.

The acquired attempt lock and event sequence define the total order; request
arrival is not promised. Expiry is reconciled before the receipt event, including
at exact equality. Two distinct commands at one expected revision have one success
and one stale conflict. If submission wins before help, its pre-help snapshot stays
unchanged when help later succeeds with a refreshed revision. If help wins, stale
submission rejects and a refreshed intake captures that grant. Equal timestamps
are ordered by event sequence. Pause/extend/defer use this same ordering. Acceptance
does not pause/end a timer or reopen an expired interval. New acceptance persists
clock anchors so a later backward clock cannot precede the accepted fact. Failed
intake rolls back expiry, timer/revision/event changes and source persistence.

## Retry, persistence and privacy

Each submission stores attempt-scoped request key/hash with a unique attempt/key
constraint. Identical key/body returns the same 201 detail and Location indefinitely
with Idempotency-Replayed: true, without a clock read or new event. Changed source,
purpose or expected_revision at the same key returns 409 IDEMPOTENCY_CONFLICT.
Replays recheck stored learner authorization and ownership. Lowering MAX_CODE_BYTES later does not invalidate an already accepted replay;
the HTTP body guard still applies before intake. No seven-day general receipt
expiry can create duplicate submissions. Detail is reconstructed from the immutable
row/snapshot; original source is not duplicated in a separate command receipt.

Submission rows have restrictive FKs for attempt, pinned versions, phase and
acceptance event, unique attempt/event sequence and SHA-256/source-byte checks.
PostgreSQL locks the attempt and validates pinned IDs/current receipt context on
insert, and refuses updates/deletes of source or evidence. No learner DELETE exists.
Existing published assets, grants and events remain immutable.

GET /api/v1/submissions/{id} resolves ownership through the parent attempt; admin
role alone never grants access. GET /attempts/{id}/submissions returns bounded
metadata summaries, not source or full evidence, with limit/purpose/cursor filters.
Default 20, max min(100, MAX_PAGE_SIZE). Descending event-sequence pagination fixes
an initial high-water mark, binds to owner/attempt/purpose, expires after one day,
and excludes later inserts. Neither read reconciles the current timer or changes
its immutable receipt. Logs contain opaque IDs/revision/policy and safe reason
codes, never source, raw request input, hidden assets or exception values.

## Responsibilities and acceptance

Domain submission intake validates byte representation, size and lifecycle. Explicit
receipt/evidence DTOs define response privacy. SubmissionRepository owns owned reads,
retry lookup, ordered page queries and inserts without commits. SubmissionService
owns transactions and composes existing AttemptService reconciliation/projection.
Thin routes validate schemas and enforce configured limits through the service.
Migration 0006 adds submissions and receipt event support, preserving B4 data.

Tests cover source boundaries/invalid syntax, ownership/roles/lifecycle, durable
replay/conflicts, parallel receipt/help/timer ordering, immutable snapshots and
PostgreSQL constraints, failed post-flush intake/retry, exact expiry, pinning/archival,
stable bounded pagination and public/error/log privacy. Run real PostgreSQL upgrade,
all regressions, Ruff, strict mypy and source/wheel checks; report deployment/crash/
execution checks as unverified. No execution or production publication bypass.
