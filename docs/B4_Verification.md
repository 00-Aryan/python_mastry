# B4 progressive assistance verification

Verified locally, 10 October 2026: Linux, Python 3.12.14, uv 0.12.23,
PostgreSQL 18.6. Rules were written before implementation in
[decision 0006](decisions/0006_progressive_assistance.md). API behavior is recorded
in the [B4 contract](REST_API_Settings_and_Contract.md#released-b4-progressive-assistance-10-october-2026)
and [generated OpenAPI](openapi.b4-progressive-assistance.json).

## Baseline and actual checks

The clean committed B3 baseline (`589db46`) passed 169 tests against real
PostgreSQL, uv sync --locked, Ruff lint/format and strict mypy before implementation.
Existing identity, immutable published assets/policies, owned attempt locks,
clock projection, transactions and retry conventions were inspected and reused.
No dependency was added; pyproject.toml, uv.lock and .python-version remain consistent.

| Check | Actual result |
|---|---|
| `uv sync --locked` | Passed |
| `TEST_DATABASE_URL=… uv run pytest -q -W error --cov=mastery_backend --cov-report=term-missing` | **203 passed**, **98% statement coverage**, no skips or warnings |
| New assistance checks | 27 real PostgreSQL integration cases and 7 pure rule/timer cases passed |
| `uv run ruff check .` | Passed |
| `uv run ruff format --check .` | Passed, 95 files |
| Strict `uv run mypy src migrations` | Passed, 64 source files |
| Normal `DATABASE_URL=… uv run alembic upgrade head` | Passed from the existing real PostgreSQL B3 baseline |
| `uv run alembic current` | `0005_progressive_assistance (head)` |
| `uv run alembic check` | No new upgrade operations detected |
| `uv build --offline` | Source and wheel built with the cached locked build backend |
| Package archive inspection | B4 migration/decision/OpenAPI, Alembic config, lock and Python version present in source; assistance modules present in wheel; no .env, virtual environment, tests, controlled clock or test verifier in wheel |
| Installed wheel smoke | Imported application from temporary wheel target with project dependencies; generated 30-path app and runtime clock returned aware UTC |
| OpenAPI | 30 paths, 34 unique operation IDs; new request/response and safe 401/403/409/503 error schemas |
| Diff review/check | Reviewed ownership, lock order, rollback, timer accounting, immutable grants and public privacy; `git diff --check` passed |

Tests use separate sessions, controlled clocks and isolated random schemas in a
disposable mastery_test database. PostgreSQL/TestClient checks ran outside the
restricted sandbox. No SQLite, timer sleeps or production publication bypass is
used. The normal migration CLI also ran against the disposable database.

## Explicit acceptance results

| Requirement | Actual evidence |
|---|---|
| Ordered ladder and release boundary | First expired-trigger request at 59,999 ms rejected; 60,000/60,001 ms granted directional. Pattern, pseudocode and partial_code required another interval. Each response contained only that stage. Terminal next required explicit solution escape. |
| Early help and irreversible history | Early first grant ended the independent interval with assistance_requested. Pause/resume/extension and later stage expiry preserved that timestamp/reason and previous grants. New phases did not restore unaided eligibility. |
| Pause/resume/restart and overdue | Waiting interval paused for an hour without advancing; resumed after extension to the exact boundary. Recreated service read persisted remaining time. Total/overdue accounting excluded all prior phase work and retained true overdue duration. |
| No countdown writes | Repeated detail and list reads before waiting-phase expiry emitted no INSERT/UPDATE/DELETE and showed the latest phase. Existing B3 no-tick and batched-list regressions also passed. |
| Duplicate/lost-response retry | Identical assistance key/body returned original grant and timer snapshot after nine days and after abandonment, with no clock sample or extra grant/event. Changed input conflicted. This simulates discarding a successful response and retrying. |
| Concurrency | Two separate sessions issuing the same key produced one grant and one replay. Distinct keys at the same revision produced one success/one stale conflict. A refreshed revision still could not bypass the next waiting interval. |
| Ownership and authorization | Other learner/admin received 404; missing identity returned 401; revoked DB learner role denied grants/history/replay with 403; disabled identity denied replay with 401. Strict confirmation and missing attempts were checked. |
| Lifecycle | Paused, already-expired attempts could receive a grant with a paused next phase. Deferred/abandoned attempts denied new grants while authorized successful retries/history remained recoverable. |
| Rollback/recovery | Injected failure after phase/event flush returned safe 500 and restored revision, phase, independent closure and grant history. Same key then succeeded. Missing assets and uniqueness conflicts rolled back reconciliation and grants; repaired assets could retry safely. |
| Missing/invalid assets and policies | Removed pinned next/solution assets returned safe 503 without mutation; intervals below/above pinned bounds rejected. Legacy timer-only and malformed policy configuration returned safe POLICY_UNAVAILABLE. |
| Full-solution escape | Active and paused attempts escaped immediately before expiry with explicit confirmation. Only terminal asset/reference solution was returned; timer closed, lifecycle remained unchanged, future new-key help/extension rejected. |
| Pinning and archival | Later published version's different assistance never replaced old attempt content. Archived question owners retained their pinned assistance; generic archived/new-start policy remained enforced. |
| Public/error privacy | Detail/list/owned question and generic question catalog/detail/version endpoints never returned hint, solution, private-test or rubric markers after a grant. Validation/state/fault errors redacted private values; ordinary hints excluded future stages and solution. |
| Database constraints/history | PostgreSQL rejected grant update/delete, backward assistance level, cleared independent closure and cross-version grant. Duplicate attempt/step returned 23505. Existing published parent/child, closed-phase, event and timer-policy protections remained intact. |
| Real migration/data | B3 timer-only policy bytes and a paused B3 attempt/phase survived downgrade-to-baseline and real upgrade to B4 unchanged, with prior-phase elapsed initialized to zero. ORM/schema comparison and upgrade replay passed. Downgrade refused stored B4 grant/new-policy attempt history (23514). |
| Regression scope | All prior question CRUD/publication/immutability/privacy, skill DAG/concurrency, timers, settings, middleware, logging and package/API regression checks passed. |

Early checks caught a VARCHAR(16) closure reason too short for assistance_requested;
migration/model width is now 32. Warning-as-error tests caught a deprecated
SQLAlchemy DISTINCT ON call; the final batched latest-phase lookup uses a grouped
maximum subquery. Initial fixture assertions expected a marker alone rather than
the actual reference-code string and were corrected. OpenAPI generation initially
omitted required database configuration; final generation supplied explicit test
settings. These failed/partial checks are not counted as successful verification.

## Resolved contract gaps and remaining limits

The user calls this assistance B4; the original roadmap calls staged help part of
B3 and submissions B4. This release follows the current request and does not start
submissions. Existing enum names directional/partial_code mean direction/logical
code steps. Publication permits skipped kinds, so runtime follows immutable stored
ordering rather than inventing missing content. Ordinary next never reveals the
full solution without confirmation. First help may be early; all later hints wait,
while confirmed solution escape bypasses waits to avoid trapping a learner.

New attempts pin pilot-assistance-1 with explicit assistance bounds. Existing B3
pilot-timer-1 attempts retain their immutable policy and cannot receive new help:
503 POLICY_UNAVAILABLE is intentional, not an unverified check. Stored assistance
receipts have indefinite replay retention, unlike the existing seven-day general
command receipts. History records grants, not visual reading; scoring remains absent.
Downgrade refuses to delete stored assistance or referenced new-policy history.

**Production publication remains unavailable until the trusted verifier is
implemented.** Controlled fixtures use the test-only transition verifier; these
checks do not validate executable reference correctness or any future verifier.
Production authentication remains disabled. No submissions, code execution,
automatic correctness, recommendations or mastery calculations were added.

Remote CI, Docker/fresh WSL setup, hosted authentication, actual dropped-network
responses, process/host crash injection, multi-host clock drift and large-scale load
were not run. Local API/database retries and service recreation were tested. No
background notification/sweeper or frontend assistance flow is implemented. Solving
clock synchronization assumptions remain those documented for B3. Package smoke
uses project dependencies rather than a fresh online dependency install.

The configured Git author is reused; no identity is invented or changed. Generated
database files, environments, caches and dist output remain ignored.

The subsequent [B5 receipt verification](B5_Verification.md) records immutable source
storage; this document remains the historical B4 assistance result.
