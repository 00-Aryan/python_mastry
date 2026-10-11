# B6b verification — blocked cloud trial

Status: **NOT VERIFIED**. Observed 12 October 2026 (Asia/Kolkata).
Sprint: [S010a](roadmap/sprints/S010a.md). Source baseline:
`fbef14449dbd990c34ca9145efc32e2640084d47`; application B6b commit `895b8e5`.
Dedicated branch: `sprint/S010a-cloud-trial-blocker`.

## Scope and invariants

Close verification of the existing B6b boundary, without rebuilding completed work.
ADR 0009 and Local_Runner_Setup require a non-root worker, Bubblewrap, user systemd,
delegated cgroup v2 controls, seccomp and a verified curated runtime. No ordinary
subprocess or Docker fallback may replace that boundary. PostgreSQL running in Docker
is database infrastructure, not learner isolation. Synthetic and skipped tests cannot
establish execution security, correctness, publication eligibility or mastery.

## Actual fresh-task preflight

The managed cloud environment was ready. Its existing PostgreSQL container was
stopped after task startup and was started explicitly. Early readiness attempts
returned no response/rejecting connections during startup; the later probe and SQL
connection succeeded. Credentials remained in ignored local files and were not logged.

| Command/check | Observed result |
|---|---|
| Explicit local-socket Docker info | Server 28.4.0 |
| `docker start mastery-cloud-postgres` | Container started |
| `docker exec mastery-cloud-postgres pg_isready -U mastery -d mastery_development` | Accepting connections after startup |
| PostgreSQL `SELECT version()` | PostgreSQL 18.6, Debian, x86_64 |
| `uv --version` | 0.12.23 |
| `uv sync --locked` | Passed on initial checkout and selected roadmap branch; 47 packages resolved |
| `uv run alembic current` | `0008_local_execution (head)` |
| `uv run alembic check` | No new upgrade operations detected |
| `uv run mastery-backend`; GET `/health/live` | HTTP 200; alive, B6b-local-isolated-runner |
| GET `/health/ready` | HTTP 200; database connected, evaluation unavailable |
| `systemctl --user is-system-running` | Exit 1, `offline` |
| `systemctl --user status` | User bus unavailable; DBUS_SESSION_BUS_ADDRESS and XDG_RUNTIME_DIR not defined |
| `command -v bwrap` | `/usr/bin/bwrap`; presence alone proves no isolation controls |
| `cat /sys/fs/cgroup/cgroup.controllers` | cpuset cpu io memory hugetlb pids; listing does not prove writable delegation |

The API smoke ran from the initial B6b checkout; API/settings files are unchanged
at the selected roadmap baseline. No external website/deployment was asserted.
The new task's published cloud setup supports API/PostgreSQL, not the mandatory
execution worker. LOCAL_RUNNER_ENABLED remains false; no worker was provisioned.

Initial sandboxed Git/Docker commands could not reach the proxy/socket; authorized
outside-sandbox commands succeeded. CLI GitHub API calls returned Forbidden; the
connected GitHub tool retrieved repository verification instead. A later sandboxed
`uv run python --version` failed on the default cache's read-only filesystem and
is not counted as a successful version check.

## Blocker-report checks

After writing the documentation-only report: `uv run ruff check .` passed;
`uv run ruff format --check .` passed (158 files); `uv run mypy src migrations`
passed (98 source files); `git diff --check` passed. These static checks do not
satisfy S010a's real-isolation acceptance requirements.

## Historical remote evidence, kept separate

The latest roadmap source has a successful exact-SHA
[run 38175538531](https://github.com/00-Aryan/python_mastry/actions/runs/38175538531).
The connector confirmed its SHA equals the baseline above. Job 114577034206 passed
locked sync, Ruff/format, mypy, migration CLI, pytest and source/wheel builds.
Isolation job 114577035514 was **skipped**. This is ordinary CI evidence, not a
fresh cloud isolation pass. Prior B0–B6a verification remains historical evidence.

## Stop condition and outstanding acceptance

The user explicitly required recording the blocker and stopping if the selected
sprint needs the unavailable worker. S010a does. No pytest suite, isolation test,
learner source, runtime probe, worker provisioning or actual crash exercise was run
in this trial. No skipped check is presented as passed. No implementation was changed.

Resume S010a on a supported host and run the full current-HEAD real-isolation plus
PostgreSQL suite with no skipped acceptance cases, migration/data and installed-worker
checks, hostile protocol/resource/privacy checks, actual worker termination and
cleanup (including unrelated workloads), stale/duplicate result protection and recovery.
Report actual crashes separately from clock-controlled lease abandonment and actual
transport interruption separately from synthetic delivery failures.

Do not mark S010a complete or advance S012 publication work. R0–R3 gates remain open.
