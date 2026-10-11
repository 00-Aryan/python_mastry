# AUTO001 — Unattended sprint automation

Starting branch: sprint/S003-remote-ci, completion record 581d251; implementation CI
c7e5812 passed. Public 00-Aryan/python_mastry remains accepted; main unchanged.

Implemented: validated state/prerequisites, atomic replacement, process lock, India
session deduplication and three-attempt budget, bounded repair/batch, separate worktree,
workspace-write noninteractive Codex, fixed independent verification, exact-SHA CI,
private logs, preserved interruptions and pending-CI recovery, disable/status/dry-run.
Windows registration uses discovered identities, interactive limited logon and no password.
See docs/automation/Sprint_Automation.md for trust boundary, paths and operating commands.

Actual local checks: locked sync/lock check, Ruff/format, strict mypy (97 source files),
19 controller tests, source/wheel builds and Alembic upgrade/current/check passed.
Full PostgreSQL regression: 320 passed, 25 real-isolation skips (the five added
controller/scheduler cases were then verified in the 19-test focused suite). The initial run
used a nonexistent database role and failed; corrected after querying current_user.
Exact-commit remote CI and actual Task Scheduler smoke remain pending. No scheduling-installed claim yet. B6b isolation remains open.

Actual Windows registration: three daily tasks created with schtasks XML under
ARYAN-KUMAR\Aryan, InteractiveToken/LeastPrivilege, India timezone. PowerShell script
policy rejected the script-based path; policy was preserved. Authenticated scheduled
smoke and final exact-commit CI remain pending.

Exact source checkpoint f574fd19c4cc7a84c7c1727be43b79d42015b977 passed remote run
[38175014670](https://github.com/00-Aryan/python_mastry/actions/runs/38175014670):
locked sync, Ruff/format, strict mypy (98 files), migration CLI, 325 passed/25 skipped,
and source/wheel builds. Isolation job skipped; gate remains open.

Real one-time scheduled smoke succeeded 12 October 2026 02:42:07 India time,
Windows LastTaskResult 0, authenticated Codex marker completed at 21:12:17 UTC,
Ubuntu uid1000. Earlier scheduled launches failed WSL_E_DISTRO_NOT_FOUND; read-only
scheduled identity/registry diagnostics confirmed the correct SID and Ubuntu. Canonical
Windows argument construction fixed the launch; a regression asserts its exact arguments.
Native launch logs reside in C:\Users\Aryan\AppData\Local\PythonMastery.
No script execution policy was changed. Latest launch/recovery refinements need their
own final exact-commit CI before enabling. No real feature sprint was launched as smoke.

Latest focused checks: 23 passed, including failed/mismatched scheduled completion
preventing enable, safe native argument/log construction and independent acceptance.
Ruff/format and strict mypy passed after these refinements.
