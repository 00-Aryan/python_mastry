# Current roadmap status

Audited 12 October 2026 (Asia/Kolkata). Read [Master_Roadmap.md](Master_Roadmap.md)
and the selected sprint record before choosing work. Status reflects evidence, not dates.

## Baseline and workflow

- Starting local HEAD: `895b8e5ff2b41ce0c868052c08221b1ec08c3dba` (`Initial commit`,
  despite being the B6b increment). Its parent is `ad75f15`; no reinitialization occurred.
- Live `origin/main` matches that SHA. GitHub confirms all eight baseline commits are
  retained, from `766756a` through B6b. Working tree initially contained only the
  user-supplied, untracked `docs/roadmap/Python_Mastery_Master_Roadmap.md`.
- Repository: [00-Aryan/python_mastry](https://github.com/00-Aryan/python_mastry), public.
  The user explicitly chose public on 12 October; S002's privacy criterion is amended.
- Canonical plan: `Master_Roadmap.md`; the imported filename is a pointer, not a second
  maintained plan. Preserve refined contracts and historical B labels.
- One sprint branch/unit at a time. Verified local commits are not automatically merged.
  Push and review evidence remain separate from implementation and local checks.

## Capability inventory

“Historical verification” means linked records, not a new local replay of those runs.
The actual remote run below verifies baseline behavior with PostgreSQL, but skips isolation.

| Capability | Implementation / commit | Verification evidence | Open limits |
|---|---|---|---|
| B0 + database foundation | `766756a`; settings, API, SQLAlchemy/Alembic | [B0](../B0_Verification.md), [B1](../B1_Verification.md); remote baseline CI | Local-only authentication; no deployed gate |
| Question storage | `0907fb7`; normalized drafts, versions and DB immutability | [B1](../B1_Verification.md), remote regressions | Trusted publication verifier unavailable; controlled test fixtures are not a bypass |
| Skill graph | `9f79410`; existing skills/mappings, DAG locks and bounded reads | [B2](../B2_Verification.md), remote regressions | Guidance only; no recommendations implemented |
| Attempts/timers | `589db46`; owned pinned attempts, durable server time | [B3](../B3_Verification.md), remote regressions | No browser workspace or deployed identity |
| Assistance | `6cebf2a`; irreversible grants, waits and full-solution escape | [B4](../B4_Verification.md), remote regressions | Grant does not prove reading; no scoring |
| Source receipts | `eb015cd`; immutable source and evidence snapshots | [B5](../B5_Verification.md), remote regressions | Receipt alone is not correctness |
| Evaluation lifecycle | `ad75f15`; dispatch intent, leases, retries and protected terminal results | [B6a](../B6a_Verification.md), remote regressions | Synthetic B6a results prove orchestration only |
| B6b runner | `895b8e5`; separate CLI, Bubblewrap/systemd/seccomp, curated runtime, outside-sandbox grading, worker authority and signed provenance | [ADR 0009](../decisions/0009_local_isolated_runner.md), [setup](../Local_Runner_Setup.md), source/tests inspected; remote static/build checks | **[B6b verification](../B6b_Verification.md) records a blocked cloud trial; historical real-runner skips are not verification; isolation gate open** |
| Publication, pilot pack, browser drafts/workspace | Planned S012–S036 | No accepted implementation evidence | No production publication bypass; no complete usable branch |
| Evidence, reviews, recommendations, statistics, hosted authentication/deployment | Planned S037 onward | No accepted implementation evidence | No mastery or release-readiness claims |

## Roadmap reconciliation

| Units | Credit / status | Remaining acceptance |
|---|---|---|
| S001 | Verified audit `ce6a023`; [record](sprints/S001.md) | Commit reference recorded in Git history |
| S002 | Verified and published; [record](sprints/S002.md); checkpoint `759ce30` | Not merged; new branch CI was in progress |
| S003 | Verified at `c7e5812`; [record](sprints/S003.md), run 38173778698 passed | Migration CLI verified; distinct real-isolation job remains skipped/open |
| S004 | ADR/backend choice implemented in B6b | Preserve ADR; carry current-host capability verification into S010a rather than rebuild |
| S005–S009 | Implemented in B6b; acceptance not fully verified | Reuse runtime, protocol, authority, leases and grader; run current-HEAD real checks |
| S010a (S010–S011 closure) | Cloud trial blocked; [record](sprints/S010a.md); no acceptance credit | Execute on supported host; distinguish actual SIGKILL from clock-controlled abandoned leases and actual transport interruption |
| S012–S114 | Planned; no completion inferred | Follow prerequisites and refined contracts |

Proposed split **S010a — B6b verification closure** is a verification unit, not new runner
features: run current-HEAD real isolation + PostgreSQL regressions, CLI migration/data
checks, package/installed-worker checks and actual recovery exercises; write
`docs/B6b_Verification.md` with exact results/capabilities and residual blockers. Include
hostile/malformed protocol cases, stale/duplicate results, output/resource/privacy
checks and unrelated-workload cleanup. If a check fails, record/reproduce it and split
a focused fix; do not waive gates or rebuild implemented units. Reconcile its effort
with S010/S011 rather than adding invented completion percentages.

## Actual verification and gaps

[Remote run 38172676544](https://github.com/00-Aryan/python_mastry/actions/runs/38172676544)
at `895b8e5` completed successfully, push-triggered. Retrieved actual job steps/logs:
locked sync, Ruff, formatting, strict mypy (92 files), PostgreSQL pytest
**306 passed / 25 skipped**, and source/wheel build succeeded. Tests exercise Alembic
migrations, but the workflow has no standalone `alembic upgrade/check` step and no
separate isolation job. `RUN_ISOLATION_TESTS` is not enabled. This is not real-runner
security or fresh WSL/deployment verification.

Local S001 checks: `uv lock --check --offline`, `uv sync --locked --offline`, Ruff,
formatting and strict mypy passed. HEAD changed only the `mastery-worker` script entry
in pyproject.toml; dependencies and Python requirement did not change. The unchanged
uv.lock is consistent and needs no artificial edit. Local pytest: **142 passed / 189 skipped**; PostgreSQL and real-runner opt-ins were
not enabled. The initial sandboxed TestClient run stalled and was interrupted; its
successful outside-sandbox rerun is recorded in S001.

Known documentation debt: README still starts with B6a and includes older endpoint/
release descriptions; its B6b section now links the blocked verification record. Refined
B6b API section and current code/OpenAPI take precedence. S001 records this debt;
it does not certify every README claim or complete the B6b verification increment.

R0/R1/R2/R3 gates remain **open**. No verified publication, complete pilot/browser flow,
evidence/recommendation loop or hosted release exists. Calendar targets are allocations,
not proof of completion; no weighted progress estimate has been assigned.

## Current trial and next action

Exactly one unit was selected on 12 October 2026 (Asia/Kolkata): **S010a — B6b
verification closure**, whose S003 prerequisite is verified. No completed sprint
was repeated and no second unit was attempted.

The new task started on `work` at `895b8e5`, equal to live `origin/main`, with no
roadmap files. Remote branch inspection recovered the latest roadmap at
`sprint/AUTO001-unattended-controller`, `fbef14449dbd990c34ca9145efc32e2640084d47`.
Its exact-commit [CI run 38175538531](https://github.com/00-Aryan/python_mastry/actions/runs/38175538531)
passed ordinary checks; its isolation job was **skipped**. This supersedes the
older pending-CI note without claiming current cloud scheduling or runner readiness.
The dedicated trial branch is `sprint/S010a-cloud-trial-blocker`, based on that SHA.

The published cloud environment's existing PostgreSQL 18.6 container started and
accepted connections. Locked sync and Alembic current/check passed. The running
API returned HTTP 200 for liveness/readiness, with database `connected` and
evaluation `unavailable`. This confirms the local API/database environment only.

**S010a is blocked:** `systemctl --user is-system-running` returned `offline`
(exit 1), and `systemctl --user status` failed because the user bus/runtime
variables are absent. The mandatory user systemd manager is unavailable.
`LOCAL_RUNNER_ENABLED=false` remains unchanged. See the exact checks and unrun
acceptance requirements in [B6b_Verification.md](../B6b_Verification.md).
No learner source, adversarial workload or replacement isolation backend was run.

Next eligible unit remains **S010a**, to resume only on a supported host with all
mandatory controls. There is **no runnable next unit in the current recorded
chain** on this host; S012 still depends on verified S010a. The protected automation
manifest/controller were not edited or invoked: their dependency-ready label is
not a claim that this host meets the capability gate. No scheduling was enabled.
This branch records the blocker for review; main remains unchanged.
