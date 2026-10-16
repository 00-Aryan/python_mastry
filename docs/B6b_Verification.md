# B6b verification reconciliation — S010a

Recorded 16 October 2026 (Asia/Kolkata). **Acceptance blocked**, not production-ready.
B6b implementation is credited at `895b8e5`; its runner/worker source and existing
real-runner tests are unchanged from that commit. This verification started from
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
