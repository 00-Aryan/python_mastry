# B3 attempt lifecycle and timer verification

Verified: 9 October 2026, Linux, Python 3.12.14, uv 0.12.23 and PostgreSQL 18.6.
Rules written before coding: [attempt timers](decisions/0005_attempt_timers.md).
API: [current contract](REST_API_Settings_and_Contract.md#released-b3-attempt-lifecycletimer-slice-9-october-2026)
and [generated OpenAPI](openapi.b3-attempt-timers.json).

## Baseline and actual checks

The clean committed B2 baseline passed **137 tests** against PostgreSQL,
`uv sync --locked`, Ruff and strict mypy (46 source files) before changes. Existing
DB roles, immutable question versions, archived-content/public projection rules,
row-lock transaction ownership and durable command replay were inspected/reused.
No dependency or independently maintained dependency list was added.

| Check | Actual result |
|---|---|
| `uv sync --locked` | Passed |
| `TEST_DATABASE_URL=… uv run pytest --cov=mastery_backend --cov-report=term-missing -W error` | **169 passed**, **98% statement coverage**, no skips/warnings |
| `uv run ruff check .` | Passed |
| `uv run ruff format --check .` | Passed, 83 files |
| Strict `uv run mypy src migrations` | Passed, 56 source files |
| Settings-based `DATABASE_URL=… uv run alembic upgrade head` | Passed from B2 in real disposable PostgreSQL |
| `uv run alembic current` | `0004_attempt_timers (head)` |
| `uv run alembic check` | No new upgrade operations detected |
| `uv build --offline` | Source and wheel built successfully with cached build backend |
| Package archive inspection | B3 migration/decision/OpenAPI, config, lockfile and Python version present in source; attempt service/clock/domain/models/repository present in wheel; no environment/virtual environments/test verifier or controlled test clock in wheel |
| Installed wheel smoke | Imported from a temporary wheel target using project dependencies; app factory generated 27-path OpenAPI and runtime SystemClock returned aware UTC |
| OpenAPI generation | 27 paths, 31 distinct operation IDs; response/error models and released capability/stage updates checked |
| Diff review/check | Checked source/transaction flow, schema guards, public projections and stage limits; no credentials/local DB artifacts staged |

Integration tests use independent sessions and isolated randomly named schemas in
`mastery_test`; no SQLite stand-in or timer sleep is used. The normal migration CLI
was also run against the disposable database. Final tightened history constraints
were reapplied from B2, with current/check rerun. Runtime startup never migrates.

## Explicit acceptance results

| Requirement | Actual evidence |
|---|---|
| Budget/type validation | 60/3600 bounds accepted; invalid/nonpositive/out-of-policy, boolean, string, null and fractional selected durations rejected; extension per-command/total bounds tested |
| Exact expiry | 59,999 ms returned 1 ms remaining; 60,000 ms expired at the exact budget boundary, not observation time; later reads retained phase duration and accumulated overdue solving |
| Expiry semantics | Lifecycle stayed active, finished_at stayed null, assistance became eligible while assistance_level stayed none; no answer result, hint or evidence was produced |
| Pause/resume/offline/restart | Accumulated 12,500 ms, excluded an hour-long confirmed pause, recreated service/session and app/TestClient from the DB, then resumed to the calculated boundary; expired resume affected total solving only |
| Extensions/history | Pre-expiry active/paused extensions respected the pinned policy; at/after expiry extension rejected; expiry/independent closure/timing accommodation stayed permanent; assessment pause/extension accommodation was retained |
| End/abandon | `/defer` ended unresolved and `/abandon` stopped voluntarily; terminal durations froze and further transitions rejected; expiry closure reason survived later ending |
| Retry and concurrency | Identical starts/transitions returned original body/receipt, incompatible keys and stale revisions conflicted; expired receipt allowed new work; two competing commands at one revision yielded one success/one conflict; concurrent identical starts stored one attempt; concurrent expiry reads recorded one expiry event |
| No per-tick writes | Before expiry repeated reads preserved stored counters/events; a multi-attempt list emitted no INSERT/UPDATE/DELETE, batched policy lookup once and sampled the solving clock once |
| Clock safety | Millisecond normalization, naive clock rejection and backward jumps covered in pure tests; backward runtime read/resume returned safe 503 without mutation |
| Authorization/ownership | Missing/disabled identity denied; stored learner-role revocation denied reads, commands and replay, including a stale service principal; spoofed role headers did not grant access; another learner/admin got 404 for owned detail/question/commands and no list items |
| Rollback | Injected post-flush start failure left no attempt/phase/event/exposure/receipt; transition failure restored state/durations/anchors/events and its key could safely retry; rejected expired extension rolled back its reconciliation, which the next read then recorded |
| Version/policy pinning | Later published question versions did not replace an existing attempt's content; a newly inserted smaller future policy did not alter pinned bounds; draft/missing/unsupported-mode starts rejected |
| Archived content | Archive denied new starts and generic detail/version reads, while existing owner retained the exact public version and could continue/end; private tests/hints/solutions/rubrics remained absent |
| Database history/constraints | PostgreSQL rejected owner/question/policy changes, history deletion/updates, timing accommodation reversal, cleared expiry/closure and edits to closed phases (23514); nonnull closure checks rejected incomplete records; duplicate phase/event sequence (23505) and missing phase parent/policy (23503) were checked |
| Migration/regressions | Real B2 curriculum revision data survived upgrade/replay/downgrade/re-upgrade; schema matched ORM; all question immutability/publication/privacy, graph concurrency and foundation checks still passed |

Initial implementation checks caught migration literal JSON being parsed as SQL
bind parameters; adding literal spacing corrected it. A historical unsupported
attempt-route test was updated to use an actually unimplemented route. An expanded
policy-pinning test exposed a missing import, corrected before the successful full
run. Final review tightened nullable SQL checks and closed-phase immutability;
regression tests and all 169 tests then passed. Failed/partial runs are not counted
as successful verification. PostgreSQL/TestClient checks needed execution outside
the restricted sandbox. Builds used cached dependencies without network changes.

## Resolved gaps and unverified limits

The decision documents unresolved ending as the existing `/defer` contract plus
explicit `/abandon`, with no manual completed/success command. It fixes budget,
extension, precision, clock rollback, phase/total duration, list, revision and
accommodation semantics. It pins the initial immutable timer-only policy rather
than exposing an unimplemented learning/evidence policy. Family first-exposure
context is persisted at start without computing evidence or mastery.

The stored expiry/closure and total durations survive app recreation; no background
notification sweeper is implemented. First expiry observation can write on GET;
ordinary ticks do not. Invalid commands roll back reconciliation too, so clients
GET current state after a conflict. Solving clocks must be synchronized between
servers; backward detection uses persisted anchors, not a persisted timestamp for
every read. Multi-host clock drift/load and real host/process crash injection were
not tested. App/session recreation and concurrent DB operations were tested.

**Production publication remains unavailable until the trusted verifier is
implemented.** Controlled published fixtures use a test-only transition verifier;
it does not validate executable correctness or any future verifier. Production
authentication remains disabled. This slice delivers only initial-phase timers;
actual disclosed-assistance history, subsequent help phases, code drafts/submissions,
execution, recommendations and mastery are not implemented or claimed verified.
Extensions never reset assistance fields, and expiry cannot be reopened; no current
route delivers hints or awards unaided credit.

Remote CI, Docker, fresh Windows/WSL setup, hosted authentication and large-scale
performance were not run. Local Linux/PostgreSQL regressions, static checks,
migrations and package checks passed. The increment uses the configured Git author;
no author identity is created or changed.
