# Unattended sprint controller

The trusted controller selects one ready unit, invokes Codex with workspace-write and
`-a never`, independently runs fixed checks, commits to `automation/daily-sprints`,
pushes without force and checks the exact pushed SHA's required `checks` job.
Main is never merged or deployed. The public repository is the accepted baseline.

## Responsibilities and trust boundary

`scripts/automation/run_sprint.py` calls the packaged controller. `state.py` validates
acyclic prerequisites, atomically replaces owner-only state and locks all operations.
`processes.py` uses argument arrays, bounded output/time and kills process groups.
`verification.py` owns commands and CI identity checks; success claims are insufficient.
The PowerShell script registers only named PythonMastery tasks. Controller tests replace
external processes for failure/recovery scenarios; they do not certify execution isolation.

The tracked plan is `docs/roadmap/sprints.json`; its initial copy becomes authoritative
`.automation/state.json`. Existing local state is never reimported or overwritten.
The trusted controller runs from the reviewed checkout, with the agent in a separate
linked worktree. Agent changes to automation, dependencies, existing tests, CI gates,
symlinks or deletions fail review. This protects orchestration from ordinary sprint
edits; it is not a security boundary against a hostile account owner. Protect the
trusted checkout and credentials with account permissions. Do not store secrets here.

Only local disposable PostgreSQL databases ending `_test` are accepted. Integration
checks mutate their data. Configuration is ignored and owner-only. No `.env` is read by
the controller. Logs store metadata, phase and safe blocker codes; source and process
output are not logged. Private structured agent results and JUnit reports remain local.
A failed command's full stdout is deliberately not retained; reproduce its fixed command
manually to diagnose without default secret logging.

Baseline verification requires at least 306 passing tests and permits at most the 25
known real-runner skips. Isolation units permit no skips. Static checks, Alembic upgrade/
current/check and source/wheel builds are also required. The selected S010a gate remains
open until actually run; publication-dependent S012 cannot advance on skipped isolation.

## Installation on this host

Discovered WSL distribution: Ubuntu; Linux user: aryan. Windows identity:
`ARYAN-KUMAR\Aryan`; timezone: India Standard Time. uv is
`/home/aryan/.local/bin/uv`, gh `/usr/bin/gh`. Installed Codex is
`/home/aryan/.vscode-server/extensions/openai.chatgpt-26.1007.21434-linux-x64/bin/linux-x86_64/codex`
(0.162.0-alpha.17.2). Its path may change after an extension update: fail closed and
review `.automation/config.json` rather than guessing a replacement.

Commit the reviewed controller before initialization. From the project root:

```bash
uv run --locked scripts/automation/run_sprint.py init \
  --codex /home/aryan/.vscode-server/extensions/openai.chatgpt-26.1007.21434-linux-x64/bin/linux-x86_64/codex \
  --database-url postgresql+psycopg://mastery@127.0.0.1:55432/mastery_test
uv run --locked scripts/automation/run_sprint.py run --dry-run
```

Initialization preserves existing automation branches/worktrees and refuses dirty
source trees. No reset/cleanup of failed work occurs. The worktree starts at the verified
S003 successor containing this controller, not the older main branch.

This host blocks PowerShell script files under its existing execution policy. Native
registration was used without changing that policy. Exact WSL controls:

```bash
uv run --locked scripts/automation/register_windows_tasks.py install --distribution Ubuntu --linux-user aryan
uv run --locked scripts/automation/register_windows_tasks.py smoke --distribution Ubuntu --linux-user aryan
uv run --locked scripts/automation/register_windows_tasks.py status
uv run --locked scripts/automation/register_windows_tasks.py disable
uv run --locked scripts/automation/register_windows_tasks.py enable
```

The native smoke uses an actual one-time trigger 30 seconds in the future. Both
registration implementations target the same names; use one. Native tasks allow battery
operation; PowerShell defaults may require AC power. The script-based alternative
requires an operator-approved script policy; do not bypass or weaken it automatically.
From Windows PowerShell, use the actual repository script if permitted:

```powershell
$script = '\\wsl.localhost\Ubuntu\home\aryan\projects\python_mastry\scripts\automation\register_windows_tasks.ps1'
& $script -Mode Install -Distribution Ubuntu -LinuxUser aryan -Project /home/aryan/projects/python_mastry -Uv /home/aryan/.local/bin/uv
& $script -Mode Smoke -Distribution Ubuntu -LinuxUser aryan -Project /home/aryan/projects/python_mastry -Uv /home/aryan/.local/bin/uv
& $script -Mode Status
```

Native task launcher logs are in `C:\Users\Aryan\AppData\Local\PythonMastery\launch-09.log`
(and `launch-14.log`, `launch-19.log`, `launch-smoke.log`); each launch replaces its file.
Persistent phase/outcome records are in `.automation/logs`. Native tasks run a fixed
cmd.exe redirection for these logs; parameters reject shell metacharacters and learner/
model-generated commands never enter this launcher. Controller output is safe metadata.

The scheduled smoke must create a fresh `.automation/scheduled-smoke.json` with the
expected Ubuntu/uid1000 and successful authenticated Codex response. Check the actual
PythonMastery-Smoke task's LastTaskResult is zero. A manually invoked CLI smoke alone
is insufficient installation evidence. Enable independently checks LastTaskResult and matches its start time to the successful
marker; a fabricated/manual marker without matching scheduled execution is refused.
Once verified, enable the controller below.

## Exact operating commands

From WSL in `/home/aryan/projects/python_mastry`:

```bash
# Enable after preflight and successful scheduled smoke
uv run --locked scripts/automation/run_sprint.py enable
# Immediate stop before the next mutation/push (does not kill a running agent)
uv run --locked scripts/automation/run_sprint.py disable
uv run --locked scripts/automation/run_sprint.py status
uv run --locked scripts/automation/run_sprint.py logs
ls -lt .automation/logs
cat .automation/scheduled-smoke.json
# Non-mutating selection, also usable while disabled
uv run --locked scripts/automation/run_sprint.py run --dry-run
# At most one bounded repair retry; consumes the same daily budget
uv run --locked scripts/automation/run_sprint.py run --slot 14 --retry S010a
# Explicit batch; shares lock, ledger, daily limit and dependency gates
uv run --locked scripts/automation/run_sprint.py run-batch --slot 19 --maximum-units 3
# Reconcile interruption or retry publication/CI for the journaled SHA
uv run --locked scripts/automation/run_sprint.py recover
```

Windows task controls (same `$script` above):

```powershell
& $script -Mode Disable
& $script -Mode Enable
& $script -Mode Status
Get-ScheduledTaskInfo -TaskName PythonMastery-Smoke
```

Use both disable commands to stop future launches and controller publication. The
controller rechecks disabled state before verification/commit/push. Changes already
committed or pushed remain preserved.

## Scheduling and recovery limits

Daily 09:00, 14:00 and 19:00 triggers use the verified Windows India timezone. Tasks
run with Interactive logon and Limited privileges; Aryan must be logged in. No password
is stored. WakeToRun requests waking; firmware/power policy may prevent it. StartWhenAvailable
requests a missed run when available. A powered-off host cannot work. Duplicate task
slots are consumed only once per India date; batch and retries share the three-attempt
limit. Each unit has two attempts maximum. Failed work stays blocked and dependent
units do not start. Unrelated ready units may run if their prerequisites are verified.

`recover` resumes push/CI for pending_ci without another agent or commit. Earlier
interrupted phases become blocked without resetting Git. Inspect the preserved worktree,
private result, starting SHA and logs before retry; dirty work requires manual review
and preservation/commit, not destructive cleanup. A crash between commit and journal
write deliberately blocks rather than guesses completion. Branch divergence rejects
push; resolve manually. Authentication/network/database failures are recorded blockers.
New acceptance profiles/ready units and repairs to automation require explicit review;
never modify the ledger to fabricate completion.

One-time operator setup: maintain an automatically started disposable PostgreSQL
service (the discovered extracted local cluster currently is manually started), logged-in
Windows/WSL account, valid Codex/gh authentication, network and supported runner/systemd
capabilities. Logout, cold boot persistence, wake from sleep and autonomous feature
completion require their own verification; launcher smoke does not prove these.

Official references: [Codex non-interactive execution](https://learn.chatgpt.com/docs/non-interactive-mode),
[Task principals](https://learn.microsoft.com/en-us/powershell/module/scheduledtasks/new-scheduledtaskprincipal),
[Task settings](https://learn.microsoft.com/en-us/powershell/module/scheduledtasks/new-scheduledtasksettingsset).


To start the discovered disposable cluster after an operator-reviewed restart, from
this checkout (never substitute a production data directory):

```bash
LD_LIBRARY_PATH="$PWD/.local-runner/postgres/usr/lib/x86_64-linux-gnu"   .local-runner/postgres/usr/lib/postgresql/18/bin/pg_ctl   -D .local-runner/postgres-data -l "$PWD/.local-runner/postgres.log"   -o '-h127.0.0.1 -p55432 -k/tmp' start
```

Configure a user PostgreSQL service separately for automatic startup. This installation
has not verified cold-boot persistence. Tasks remain fail closed if the database is absent.
