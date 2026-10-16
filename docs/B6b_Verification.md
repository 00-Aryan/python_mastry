# B6b verification reconciliation — S010a

Recorded 16 October 2026 (Asia/Kolkata). **Local B6b verification acceptance Verified**
after the explicit S011 reconciliation below; not production-ready. Historical Blocked
snapshots remain below as evidence, rather than being silently rewritten.
B6b implementation is credited at `895b8e5`; at S010a start its runner/worker source
and existing real-runner tests were unchanged from that commit. S010b updates follow below. This verification started from
`d30c5d9dc4541068cd027186d20f52e303d940ad`, the documentation-only S003 closeout.
S003 implementation verification remains separately pinned to
`fbef14449dbd990c34ca9145efc32e2640084d47`, remote CI run 38175538531
(329 passed / 25 skipped). That older run does not prove real isolation.

Four pre-existing dirty AUTO001 files were retained byte-for-byte. No automation
controller, machine-readable sprint state, scheduling, API settings, worker identity,
publication policy or production configuration was changed. Local full-suite results
include that preserved working tree; they are not exact-commit remote CI evidence.

## Capability and startup evidence

| Check | Actual observation |
|---|---|
| Host | WSL2 x86_64, kernel `6.18.33.2-microsoft-standard-WSL2`, non-root uid1000 |
| Tools | Python 3.12.14, uv 0.12.16, Bubblewrap 0.11.1, systemd 259.5 |
| Coding sandbox | `systemctl --user is-active default.target` denied bus access with Operation not permitted |
| Authorized host check | PID1 systemd; user default.target active; cgroup2 rw/nsdelegate; cpu/memory/pids controllers present |
| Existing runtime | `mastery-worker probe --runtime .local-runner/runtime` failed closed: Trusted sandbox bootstrap is unavailable |
| Existing runtime explanation | Sealed image bootstrap hash `c80d8b535b2f8918a277c1208d800d662765ba87ebd13045170f488c4bd034cb` differs from current source `803c23ef82b2d479494007cf6c669b26bf2551bae3e6e42f35bb8d0e05be6675`; old bootstrap lacks READY handshake |
| Fresh test runtime | Existing test fixture builds a new sealed image; mandatory startup, live cgroup limits, namespaces, seccomp and privilege probes passed |
| PostgreSQL | Existing disposable PostgreSQL 18 cluster at 127.0.0.1:55432, mastery_test; started for verification; no application database used |

The missing user bus inside the coding sandbox is not a missing host capability.
Host checks used authorized execution outside that coding sandbox, while retaining the
complete learner Bubblewrap/systemd/seccomp profile. No unrestricted learner process
was substituted. Tests provision only controlled fixture identities and published assets;
no operational worker was provisioned, served or enabled. The old runtime was preserved.
Rebuild to a new reviewed runtime path before any future operator provisioning; do not
reuse the old image or overwrite a pinned image to make the probe pass.

## Actual commands and results

Commands ran through uv with `UV_CACHE_DIR=/tmp/mastery-uv-cache`. PostgreSQL opt-in used
`TEST_DATABASE_URL=postgresql+psycopg://mastery@127.0.0.1:55432/mastery_test`.

| Check | Result |
|---|---|
| `uv sync --locked --offline`; `uv lock --check --offline` | Passed; lock/dependency/runtime files unchanged |
| `uv run ruff check .`; `uv run ruff format --check .` | Passed; latest formatting inventory 160 files |
| Strict `uv run mypy src migrations` | Passed, 98 source files |
| Normal PostgreSQL regressions, `uv run pytest -q -W error` | **329 passed, 25 skipped**, 75.68 seconds; skips explicitly exclude real isolation |
| Alembic CLI, scoped disposable DATABASE_URL | upgrade head/current/check passed, `0008_local_execution (head)`, no new upgrade operations |
| First opt-in real files, `pytest tests/test_local_isolation.py tests/integration/test_local_runner.py -x -q -W error` | **17 passed, 1 failed**; stopped at cancellation race, 13.21 seconds |
| Existing complete opt-in suite, `RUN_ISOLATION_TESTS=1 ... pytest -q -W error` | **354 passed, no skips**, 93.11 seconds; existing cancellation test happened to pass |
| Added `tests/test_runner_verification.py` with real isolation | **7 passed**, no skips, 5.27 seconds |
| Isolated cancellation reproduction | **1 failed**, 2.41 seconds; same bootstrap-unavailable versus cancelled assertion |
| Final complete suite including added cases | **361 passed, zero skips**, 117.53 seconds; reproduced cancellation failure remains a blocker |
| `uv build` | Source/wheel built; initial offline attempt lacked cached uv_build, authorized fetch resolved it |
| Installed wheel smoke | Installed with --no-deps to ignored target; imported worker from that target, verified CLI help/entrypoint and disabled-runner default using project dependencies; installed CLI built a new runtime and its full host isolation probe passed |
| Package privacy/inventory | Wheel excludes tests/.env/worker credential; source includes lock, AGENTS, migration 0008 and v2 schema |

Local ignored evidence is under `.local-runner/s010a-evidence/`: JUnit and summaries
`regression`, `real-isolation`, `full-real`, `protocol-cleanup`,
`cancellation-reproduction`, `final-real`; preserved-file hashes are recorded there too.
No ignored logs or credential files are committed. Installed-wheel smoke does not
claim a fresh dependency installation or deployed worker verification.

## What real checks establish

Existing tests executed correct, incorrect, syntax-error and runtime-error submissions
through the real sandbox and PostgreSQL adapter. They checked immutable version/policy/
source/runtime pins, signed provenance, duplicate delivery, unsigned/forged/stale results,
readiness expiration/revocation, learner/worker identity separation, safe status responses
and B6a-to-B6b data preservation. Incorrect code stayed distinct from infrastructure failure.

Actual isolated workloads exercised infinite loops, excessive output, 512 MiB allocation,
process and socket creation denial, tmpfs exhaustion, private/host filesystem denial,
read-only bootstrap, fresh storage/environment, capability dropping, no_new_privs,
seccomp and credential/expected-asset exclusion. Added tests rejected nonfinite/non-JSON/
overdeep results, expression-like and binary stdout without evaluation/deserialization,
and oversized input before workload creation. A real timed-out workload was reclaimed
while an unrelated trusted sleep service remained active; both were scoped and cleaned up.

Existing SIGKILL tests actually killed OS worker processes and observed independent
service termination and a retained PostgreSQL running lease before recovery. These are
real process-termination checks. However, their readiness markers occur after live
control verification, not an explicit learner-entry acknowledgement. Do not overclaim
proof of the exact instruction executing at kill time. Recovery's 30-second lease and
5-second backoff are advanced with a controlled clock, not observed by waiting real time.
The abandoned-completed-dispatch case deliberately discards a real result and replays a
new generation; it is not a killed worker or interrupted network connection.

## Blocking failure and remaining acceptance

`test_real_cancellation_stops_complete_unit` failed in the initial opt-in run and an
independent reproduction, while passing in the full run. Its event is set by
`verify_controls`, before the trusted READY handshake. Cancellation after a fixed 0.1 s
can therefore stop the service during bootstrap; execute then raises
`Trusted sandbox bootstrap is unavailable` instead of the expected `cancelled`.
This ordering explains the observed failure; a deterministic phase-aware regression
and reviewed implementation/test contract decision are still required. No production
fix, relaxed assertion, skipped case or disabled control was introduced here.

**S010a stays Blocked.** Next ready focused card is S010b, cancellation phase ordering.
After that, rerun all real checks with no skips/failures and reconcile S010a. Explicit
commit/acknowledgement-loss recovery with a real interrupted process/database response
and measured wall-clock lease recovery remain unverified S011 acceptance; existing
clock-controlled replay tests cannot replace them. The seven added opt-in cases add seven explicit skips to non-isolation runs; the existing
AUTO001 baseline verifier hard-codes the earlier skip budget/allowlist. That policy will
need separate review before future baseline automation; it was preserved unchanged as
requested. No skipped new check is represented as passed.

Remote capable-host CI, cold WSL
startup, deployed authentication/isolation, publication verification and production
readiness are unverified. This shared-kernel local sandbox is not VM/kernel security
certification. S012 publication-dependent work remains blocked.


## S010b — bounded cancellation correction

S010a checkpoint `7d05e81` remains historically Blocked. S010b started from that SHA,
reproduced the original cancellation failure once more before changing code, and then
separated explicit stop intent from finally/resource termination. Requests during
mandatory validation are latched; validation errors retain their meaning. Pending
cancellation is ordered at READY and source-send boundaries under a reentrant lock.
Malformed nonempty handshakes, uncancelled EOF/timeouts and real broken pipes stay
failures; this is not catch-all relabelling. Explicit cancellation stays latched on an
instance, and launch/cleanup paths clear its active state. See ADR 0009 and the
[S010b record](roadmap/sprints/S010b.md) for contract decisions and exact tests.

Thirteen deterministic supervisor tests use process substitutes only. The real
cancellation test uses barriers at controls, READY and confirmed learner entry (a
fixture stderr marker), replacing the fixed sleep. Five consecutive real-phase runs
passed all 15 real cases; runs 2–5 also passed the 13 deterministic cases each.
The complete PostgreSQL/real-isolation suite passed **376 tests, no skips**, 88.22 s.
Locked sync/lock check, Alembic upgrade/current/check at 0008, Ruff/format (161 files),
strict mypy (98 source files), source/wheel build and installed-wheel fresh runtime
probe passed. No operational worker was provisioned or enabled. The supervisor change
naturally changes the existing isolation-profile hash; immutable old policy pins remain
unchanged. Future operator provisioning must use the reviewed new profile.

Exact implementation `cca8c50e6af18115ba6d41ec7da980d7407a0d5c` passed
[remote run 38881670423](https://github.com/00-Aryan/python_mastry/actions/runs/38881670423): locked sync,
migrations, Ruff/format, strict mypy, **342 passed / 34 skipped**, source/wheel builds.
The separate isolation job was skipped; the local 376-passed real run remains separate
evidence. S010b is **Verified** for its bounded scope. Local JUnit/logs are
ignored in `.local-runner/s010b-evidence/`. Existing dirty AUTO001 files remain unchanged.
The S010b cancellation blocker is resolved, but S010a stays **Blocked** for
real acknowledgement-loss and wall-clock lease recovery. Neither was implemented or
verified here. Remote isolation certification, cold-start/deployed checks and production
readiness remain unverified. Next scope is remaining S011 recovery evidence, not begun.

## S011 — real recovery gap closure

Starting implementation baseline `3d105be`, with S010b fix `cca8c50` unchanged.
New verification uses the production worker/adapter and SystemClock in real child
processes. A test-only loopback PostgreSQL proxy withholds a selected actual server
COMMIT reply and closes the connection. This is real wire acknowledgement loss, not
an ignored Python return or fabricated adapter result. Only the trusted disposable DB
connection uses plaintext for frame inspection; learner network isolation is unchanged.

The targeted run passed four cases (99.45 s): provenance-commit acknowledgement loss,
terminal-commit acknowledgement loss, and SIGKILL after completed dispatch / confirmed
running learner entry. Independent connections observed durable state. Lost provenance
acknowledgement requeued infrastructure work without marking the learner incorrect;
lost terminal acknowledgement retained one final result. Authentic expired/stale results
were rejected, generation/token changed after real 30-second lease and 5-second backoff,
and duplicate application could not create a second terminal event. Initial killed-worker
scenarios took 36.72 / 38.27 s; the strengthened full run additionally tests actual
heartbeat expiry, five-second recovery span and post-recovery credential revocation.

The S010a acceptance reconciliation below is explicit. Its status is not changed until
all required current checks and exact-commit publication evidence are inspected.

| S010a requirement | Evidence / review |
|---|---|
| Reuse existing runner and boundaries | No production code change in S011; source remains S010b, no API executor/callback |
| Mandatory startup and immutable runtime/profile | Fresh isolated test runtime and installed-wheel mandatory probe; policy pins unchanged |
| Actual correct/incorrect/syntax/runtime grading | Existing real PostgreSQL runner tests, repeated in complete suite |
| Resource/process/network/filesystem/privacy/fresh state | Existing real isolation/protocol tests, repeated in complete suite |
| Hostile/malformed bounded protocol | S010a's seven extra real checks plus existing JSON rules, repeated |
| Cancellation and full cleanup | S010b's three deterministic real phases; targeted 16 checks passed, full rerun |
| Unrelated workload survival | S010a real sentinel test, repeated; no production service touched |
| Real worker crash during learner execution | New child waits for an actual learner stderr marker before SIGKILL; unit/cgroup inspected |
| Actual acknowledgement loss | New one-shot wire proxy suppresses actual PostgreSQL COMMIT response at provenance and terminal transactions |
| Real-time lease/backoff and stale authority | SystemClock plus actual waits, authentic stale signatures/new generations/revocation checks |
| Duplicate delivery and terminal immutability | Durable provenance/cache and one-terminal-event assertions, existing DB guards |
| Upgrade/data/schema checks | Existing migration/data tests plus CLI upgrade/current/check at 0008 |
| Packages/static/locked dependencies | Current sync/check, Ruff/format, strict mypy, builds, artifact byte/privacy inventory and installed probe passed |
| Full real-isolation regression, zero skips | **380 passed / no skips**, 200.86 s; all current real checks repeated |

Limits remain: a local shared-kernel boundary is not production security certification.
These tests cover selected commit-loss windows, not every network/database failure.
TLS/remote runner transport, host reboot, cold WSL setup, deployed controls and production
readiness remain unverified and are not implied by local gap closure. Finite measurements
are not clock-drift or load certification. No scheduling or operational worker changed.

Final strengthened S011 run: **380 passed, no skips**, 200.86 s. Both killed-worker
cases verified actual stale heartbeat expiry, expired authentic results, new lease
nonces/generations, duplicate terminal protection and credential revocation. Actual
elapsed totals were 36.42 / 39.56 s, with full five-second backoff spans checked using
monotonic time. Unit/cgroup cleanup and post-suite absence of active temporary services
were confirmed. Package/static/locked dependency/migration checks passed as above.
No production/cancellation source changed from `3d105be`. All S010a local acceptance
rows have concrete evidence; exact-commit CI passed as recorded below. This explicit
reconciliation, not S011 completion alone, is the basis of any status change.

### Final local acceptance decision

All rows of the S010a matrix above are supported by actual current checks; none is
closed merely because S011 is complete. S010a and S011 are **Verified for their local
scopes** at verification checkpoint `9ca97d2577d4d8619f20595b9b1253881f8188a3`.
[CI run 38938550175](https://github.com/00-Aryan/python_mastry/actions/runs/38938550175)
passed locked sync, migration CLI, Ruff/format, strict mypy and builds, with
**342 passed / 38 skipped**, 134.93 s. The hosted isolation job was skipped;
**380 passed / no skips** on the actual capable host remains separate evidence.
The four S011 cases add four explicit non-isolation skips; the existing AUTO001
verification policy still needs separate review and was preserved unchanged.

Current source has no S011 production/cancellation change. The explicit wire faults,
real SystemClock waits, signed stale-result checks and cleanup observations close the
previous local acknowledgement-loss/wall-clock gaps. They do not establish TLS/remote
runner transport, reboot/cold-start/deployed behavior, arbitrary distributed failures
or production isolation certification. Publication remains disabled; next card S012
is not implemented by this work. No operational worker or scheduling changed.
