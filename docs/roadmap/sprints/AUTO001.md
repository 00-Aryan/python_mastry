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
17 controller tests, source/wheel builds and Alembic upgrade/current/check passed.
Full PostgreSQL regression: 320 passed, 25 real-isolation skips (the three added
controller cases were then verified in the 17-test focused suite). The initial run
used a nonexistent database role and failed; corrected after querying current_user.
Exact-commit remote CI and actual Task Scheduler smoke remain pending. No scheduling-installed claim yet. B6b isolation remains open.
