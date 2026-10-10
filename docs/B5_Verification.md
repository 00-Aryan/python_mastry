# B5 immutable submission verification

Verified locally, 10 October 2026: Linux, Python 3.12.14, uv 0.12.23 and PostgreSQL
18.6. Rules were documented before implementation in
[decision 0007](decisions/0007_immutable_submissions.md). Read the
[B5 API contract](REST_API_Settings_and_Contract.md#released-b5-immutable-source-receipts-10-october-2026)
and [generated schema](openapi.b5-immutable-submissions.json) for exact input/output.

## Baseline and actual checks

The clean committed B4 baseline (`6cebf2a`) passed 203 real PostgreSQL/regression
tests, uv sync --locked, Ruff and strict mypy. Existing identity/ownership, pinned
published assets/policies, attempt/assistance clocks, row locks, transaction ownership
and durable retry handling were inspected and reused. No dependencies were added;
pyproject.toml, uv.lock and .python-version remain consistent.

| Check | Actual result |
|---|---|
| `uv sync --locked` | Passed |
| `TEST_DATABASE_URL=… uv run pytest -q -W error --cov=mastery_backend --cov-report=term-missing` | **244 passed**, **98% statement coverage**, no skips/warnings |
| New submission checks | 31 real PostgreSQL integration cases and 10 pure source/lifecycle cases passed |
| `uv run ruff check .` | Passed |
| `uv run ruff format --check .` | Passed, 108 files |
| Strict `uv run mypy src migrations` | Passed, 72 source files |
| Normal `DATABASE_URL=… uv run alembic upgrade head` | Passed from the existing real B4 baseline |
| `uv run alembic current` | `0006_immutable_submissions (head)` |
| `uv run alembic check` | No new upgrade operations detected |
| `uv build --offline` | Source and wheel built with cached build backend |
| Archive inspection | Source includes B5 migration/decision/OpenAPI, Alembic config, lockfile, AGENTS and Python version; wheel includes submission API/service/domain/persistence modules; no .env, virtual environment, tests, controlled clock or test verifier in wheel |
| Installed wheel smoke | Imported from a temporary wheel target using project dependencies; generated 32-path/37-operation schema; invalid-syntax source intake hashed without interpretation; runtime clock returned aware UTC |
| OpenAPI generation | 32 paths, 37 distinct operation IDs; explicit receipt models and 401/403/409/413 error responses |
| Diff review/check | Reviewed source handling, snapshot facts, ownership, lock/commit boundaries, DB guards and scope; `git diff --check` passed |

Tests use independent sessions, deterministic clocks and isolated random schemas
in the disposable mastery_test database. PostgreSQL/TestClient checks required
execution outside the restricted sandbox. No SQLite substitute, timer sleep,
production publication bypass or learner-code runner was used.

## Explicit acceptance results

| Requirement | Actual evidence |
|---|---|
| Source receipt | Exact UTF-8 source, CRLF endings, byte count, SHA-256, server acceptance time and immutable pins persisted; status received/evaluation not_requested returned, with no executed/correctness/success outcome |
| Invalid Python intake | Broken syntax, wrong implementations and source containing os._exit were accepted unchanged without interpreting/executing it; process continued normally |
| Payload boundaries | Exactly 65536 bytes accepted and 65537 rejected with 413; multibyte source counted bytes rather than characters; whole oversized JSON rejected by existing body guard; blank/NUL/lone surrogate source returned safe 422; invalid fields/purpose/revision and caller identity/evidence fields rejected |
| Lifecycle | Active and paused receipts accepted; paused elapsed time stayed frozen; expired and full-solution-exposed active attempts could submit without independent-success claims; defer/abandon and reserved completed rejected new intake |
| Immutable acceptance evidence | Snapshot captured exact phase timer, total/overdue duration, independent closure, assistance level/grant IDs, mode, accommodation and familiar-family context. Later assistance left the earlier detail byte-equivalent at JSON level; subsequent receipt captured the granted stage |
| Exact expiry ordering | Intake at 59,999 ms captured 1 ms remaining; at 60,000/60,001 ms captured exact expiry before receipt event. Assistance stayed none and no automatic outcome/disclosure occurred |
| Concurrency | Parallel same-key submissions created one immutable identity and one replay. Distinct keys at one revision had one success/one stale conflict. Submission races with help, pause, extension and abandonment used the same ordering; fresh retry captured the committed state |
| Durable retry recovery | Identical key/body returned original 201/detail/Location after nine days, changed source/purpose/revision conflicted, lower MAX_CODE_BYTES did not invalidate replay, and terminal transition retained exact authorized recovery without a clock read |
| Multiple identities | Identical source under distinct keys created distinct submission UUIDs, with independent receipt event sequences; no observation or grading record was produced |
| Authorization | Other learner/admin received 404 for intake/detail/list/replay; missing/disabled identity returned 401 and revoked DB learner role denied reads/replay with 403; no source/private markers leaked in denials |
| Rollback/retry | Injected post-insert/flush failure restored source count, timer materialization/expiry, attempt revision/event sequence and closure; same key retried successfully. Corrupt hash/byte count/policy/grant evidence and duplicate keys returned safe storage conflicts and rolled back all new facts |
| PostgreSQL immutability | UPDATE/DELETE of source, hash, evidence, pins, acceptance time and retry key rejected with 23514. Insert-time context, hash/byte checks, restrictive FKs and request/event uniqueness accompanied the service rules |
| Pagination | Descending event order worked with equal acceptance timestamps; initial high-water cursor excluded later inserts, without duplicates/gaps. Purpose/attempt/owner binding, expiry, malformed cursors, bounds and MAX_PAGE_SIZE were checked. Summary SQL/response omitted source/evidence columns |
| Clock/read behavior | Acceptance persisted clock anchors; an immediately earlier clock returned safe 503 without a second receipt and could retry after synchronization. Detail/list read only immutable stored facts, with no solving-clock sample or writes |
| Version/archival policy | Later question versions and inserted future policy did not change pins; archived existing owned attempts could still submit/read history; old receipt remained unchanged |
| Privacy/logging | Submission metadata/evidence never loaded/exposed private tests, hints, reference solution or rubrics. Public question/attempt endpoints excluded learner source. Structured receipt logs included opaque submission ID but no source/private assets; validation/fault/conflict errors were safe |
| Migration/data | Real B4 paused attempt, assistance grant and both phases survived downgrade-to-B4/upgrade/replay unchanged; ORM/schema comparison passed. Downgrade refused stored submission history (23514) and retained data/head after rollback |
| Regressions | All earlier content publication/immutability, skill graph, timer/assistance, identity, settings, middleware and logging tests passed |

An intermediate test-file expansion lost imports previously removed as unused by
Ruff; those tests initially failed with NameError. Imports were restored and the
complete suite passed. Final review tightened insert-time current-phase/closure/
remaining/overdue evidence checks, then reran all 244 tests. Failed/partial runs
are not counted as successful checks.

## Resolved gaps and unverified limits

This user-requested B5 accepts receipts rather than building the evaluator/scoring
milestones called B4/B5 in the original plan. public_run/assessment are stored intent
labels, both supported for current practice/assessment attempts. Nonblank source is
required for both; drafts are not implemented. Syntax/correctness are deliberately
not classified at intake. Source must be representable as PostgreSQL UTF-8 text.

Receipt status is received and evaluation not_requested; no pending assessment job
exists, so the future pending-evaluation help lock does not activate. Event sequence
and lock acquisition define order, not network arrival or equal timestamps. Durable
attempt/key replay is indefinite; HTTP body limits still apply before replay. Evidence
snapshots are preserved for future decisions and do not compute eligibility or mastery.
No new policy replaces existing attempt pins. Downgrade refuses to erase submissions.

Execution, isolation/grading, evaluation queues/workers, recommendations and mastery
are absent and unverified by design. Production publication still awaits a trusted
reference verifier; controlled test fixtures validate transitions, not executable
reference correctness or any future verifier. Deployed authentication remains disabled.

Remote CI, Docker/fresh WSL installation, actual socket-response loss, process/host
crash injection, multi-host clock drift and production-scale load were not run.
Lost-response recovery is simulated by ignoring a successful response and retrying;
real DB transactions/concurrency and service/session recreation are tested. Package
smoke uses project dependencies, not a fresh online dependency installation.

The configured Git author is reused without changing identity. Credentials, .env,
virtual environments, caches, dist output and local database artifacts remain ignored.

B6a subsequently adds separate owned evaluation admission and job history; see
[B6a verification](B6a_Verification.md). The B5 checks above remain the historical
receipt-only verification, not proof of runner execution or security.
