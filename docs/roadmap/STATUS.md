# Current roadmap status

Initial audit: 12 October 2026. S003 closeout: 15 October 2026; S010a reconciliation: 16 October 2026
(Asia/Kolkata). Read [Master_Roadmap.md](Master_Roadmap.md)
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
| B6b runner | `895b8e5`; separate CLI, Bubblewrap/systemd/seccomp, curated runtime, outside-sandbox grading, worker authority and signed provenance | [ADR 0009](../decisions/0009_local_isolated_runner.md), [setup](../Local_Runner_Setup.md), source/tests inspected; remote static/build checks | [B6b reconciliation](../B6b_Verification.md): real host checks executed locally; local verification closure **Verified** at `9ca97d2` after explicit S010a/S011 audit; remote/deployed isolation certification remains unverified |
| Publication verification artifacts | `955b082`; local isolated reference CLI, immutable private snapshot/report pins | [S012](sprints/S012.md): 394 local passed/no skips; exact-commit remote CI passed | Publication consumption is S013; stronger quality validation is S014; no deployed attestation |
| Publication transition, pilot pack, browser drafts/workspace | Planned S013–S036 | No accepted completion evidence | No production publication bypass; no complete usable branch |
| Evidence, reviews, recommendations, statistics, hosted authentication/deployment | Planned S037 onward | No accepted implementation evidence | No mastery or release-readiness claims |

## Roadmap reconciliation

| Units | Credit / status | Remaining acceptance |
|---|---|---|
| S001 | Verified audit `ce6a023`; [record](sprints/S001.md) | Commit reference recorded in Git history |
| S002 | Verified and published; [record](sprints/S002.md); checkpoint `759ce30` | Not merged; new branch CI was in progress |
| S003 | **Verified** implementation baseline `fbef144`; [record](sprints/S003.md), exact-commit run 38175538531 passed | 329 passed / 25 skipped; separate isolation job skipped; dirty AUTO001 changes excluded |
| S004 | ADR/backend choice implemented in B6b | Preserve ADR; carry current-host capability verification into S010a rather than rebuild |
| S005–S009 | Implemented in B6b; acceptance not fully verified | Reuse runtime, protocol, authority, leases and grader; run current-HEAD real checks |
| S010–S011 | Adversarial/crash test code exists; verification incomplete | Execute on supported host; distinguish actual SIGKILL from clock-controlled abandoned leases and actual transport interruption |
| S010a | **Verified locally** at `9ca97d2`; [explicit acceptance audit](sprints/S010a.md) | Local 380 passed/no skips; remote/deployed certification excluded |
| S010b | **Verified** at `cca8c50`; [record](sprints/S010b.md); remote run 38881670423 passed | Local 376 passed/no skips; remote 342 passed/34 skips; S010a recovery gaps remain |
| S011 | **Verified** at `9ca97d2`; [record](sprints/S011.md); CI 38938550175 passed | Actual wire acknowledgement-loss and elapsed-time recovery; no production readiness claim |
| S012 | **Verified locally** at `955b082`; [record](sprints/S012.md); CI 38945673491 passed | 394 local passed/no skips; 348 remote passed/46 isolation skips; publication integration remains S013 |
| S013 | **Awaiting exact-commit CI**; [record](sprints/S013.md) | 429 local passed/no skips; configured publication only; remote CI pending |
| S014–S114 | Planned; no completion inferred | Follow prerequisites and refined contracts |

**S010a — B6b verification closure** is a verification unit, not new runner
features: run current-HEAD real isolation + PostgreSQL regressions, CLI migration/data
checks, package/installed-worker checks and actual recovery exercises; write
`docs/B6b_Verification.md` with exact results/capabilities and residual blockers. Include
hostile/malformed protocol cases, stale/duplicate results, output/resource/privacy
checks and unrelated-workload cleanup. If a check fails, record/reproduce it and split
a focused fix; do not waive gates or rebuild implemented units. Reconcile its effort
with S010/S011 rather than adding invented completion percentages.

## Actual verification and gaps

S003 closeout inspected current HEAD `fbef14449dbd990c34ca9145efc32e2640084d47`
on `sprint/AUTO001-unattended-controller`. The live origin branch matches exactly;
main remains `895b8e5`. [Remote run 38175538531](https://github.com/00-Aryan/python_mastry/actions/runs/38175538531)
completed successfully for this exact SHA. Its required `checks` job and actual logs
confirm locked sync, PostgreSQL 18, Alembic upgrade/current/check at `0008_local_execution`,
**329 passed / 25 skipped**, Ruff, formatting (157 files), strict mypy (98 source files),
and source/wheel builds. The distinct isolation job was skipped: runner isolation is
explicitly unverified. This exact-commit run, not the older environment result below,
is the basis for S003 **Verified**.

Four existing AUTO001 working-tree changes remain outside that CI evidence:
`docs/roadmap/sprints.json`, `src/mastery_backend/automation/controller.py`,
`src/mastery_backend/automation/state.py`, and `tests/automation/test_controller.py`.
They were preserved unchanged. This documentation-only closeout has no S003 blocker
or repair. The S003 documentation-only closeout commit follows the audited SHA and
does not replace its implementation verification reference.
No AUTO001 acceptance or current scheduling-state claim is made by this closeout.

Historical evidence follows; statements about earlier workflow gaps describe those
older commits, not the current S003 pipeline.

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
release descriptions. Its previously missing B6b verification link now resolves to the
S010a reconciliation, which records a blocker rather than certifying completion. Refined
B6b API section and current code/OpenAPI take precedence. S001 records this debt;
it does not certify every README claim or complete the B6b verification increment.

R0/R1/R2/R3 gates remain **open**. No verified publication, complete pilot/browser flow,
evidence/recommendation loop or hosted release exists. Calendar targets are allocations,
not proof of completion; no weighted progress estimate has been assigned.

## S010a local reconciliation — 16 October 2026

S003 records were committed separately at `d30c5d9`; its implementation verification
remains `fbef144`/run 38175538531. Authorized host checks found active user systemd and
mandatory cgroup controls; a stale runtime failed closed, while fresh test runtimes
passed startup. No sandbox control was removed and no operational worker was enabled.

Local PostgreSQL regressions: **329 passed / 25 skipped**. Opt-in complete existing
suite: **354 passed / no skips**, including actual OS worker SIGKILL and resource/privacy
checks. Seven new real protocol/cleanup checks passed. However, cancellation failed
in the initial opt-in run and independently reproduced (bootstrap unavailable instead
of cancelled). This intermittent failure blocks S010a despite the successful full run.
Final combined suite: **361 passed / no skips**; the independent failure still blocks
acceptance. Static, migration, locked dependency, build and installed-wheel checks passed. Local working-tree evidence
is distinct from remote exact-commit CI; no new remote isolation pass is claimed.

## S010b cancellation ordering

Starting HEAD `7d05e81`; S003 documentation `d30c5d9` stays distinct from its verified
implementation baseline `fbef144`. The original cancellation failure reproduced before
the bounded fix. Explicit cancellation is now ordered around mandatory validation,
READY and source send; cleanup/resource stops do not manufacture cancellation intent.
Genuine control/bootstrap/pipe failures retain their meaning. No authority/lease changes.

Local checks passed: 13 deterministic supervisor cases; five consecutive three-phase
real cancellation matrices; **376 PostgreSQL/real-isolation regressions with zero skips**;
locked sync/lock check, migrations at 0008, Ruff/format, strict mypy and package/installed
probe checks. Exact implementation `cca8c50` passed [CI run 38881670423](https://github.com/00-Aryan/python_mastry/actions/runs/38881670423)
with **342 passed / 34 skipped**, plus all required quality/migration/build checks.
The separate remote isolation job skipped; local real-isolation evidence remains distinct.
Existing four AUTO001 files were
preserved byte-for-byte and excluded from this unit's commits.

## S011 real recovery and S010a reconciliation

Verification checkpoint `9ca97d2577d4d8619f20595b9b1253881f8188a3` adds only tests
and records; production worker/cancellation code is unchanged from `3d105be`/S010b.
Real loopback PostgreSQL COMMIT replies were withheld after durable server completion
at provenance and terminal transactions. Real killed workers recovered after unchanged
30-second leases/five-second backoff, with actual stale signatures, nonce/generation,
readiness, duplicate/terminal and revoked-credential checks. Independent connections
verified durable state; running unit/cgroup cleanup was observed.

Targeted recovery: 4 passed; cancellation: 16 passed. Full PostgreSQL/real-isolation
suite: **380 passed / zero skips**, 200.86 s. Static/format/type, locked dependencies,
migrations/data checks and packages/installed mandatory probe passed. Exact-commit
[CI run 38938550175](https://github.com/00-Aryan/python_mastry/actions/runs/38938550175)
passed with **342 passed / 38 skipped** plus required quality/migration/build checks.
The remote isolation job was skipped; local capable-host evidence is distinct.

S010a is **Verified for its local scope** only after the [full criterion matrix](../B6b_Verification.md)
was reconciled against current real evidence; S011 completion alone did not close it.
Historical failures and Blocked checkpoints remain recorded. Remote capable-host CI,
cold-start/deployed behavior and production security certification remain unverified.
All four dirty AUTO001 files and scheduling/local state were preserved unchanged.

## Next action

**S013 — Safe publication transition** has passed local acceptance and awaits
exact-commit CI; see its [record](sprints/S013.md). S014 is next once S013 closes,
not started. Local publication requires fresh approved S012 evidence; missing
configuration/usable evidence retains 503. No operational worker, AUTO001 continuation,
scheduling, merge or deployment changes occurred.


## S012 local acceptance — 16 October 2026

Separate local trusted reference-verification artifacts are implemented; no API
publication integration is enabled. The CLI captures canonical private draft bytes,
runs reference examples/tests under unchanged B6b isolation outside transactions,
and stores append-only hash/version-pinned bounded reports. Migration 0009 reuses
immutable evaluator policies and refuses report-history deletion. See
[the acceptance record](sprints/S012.md) and [decision 0010](../decisions/0010_publication_artifacts.md).

Final local PostgreSQL/real-isolation suite: **394 passed, zero skips**, 218.14 s,
including cancellation and real recovery regressions. Locked dependencies,
Ruff/format (174 files), strict mypy (103 files), migrations/no drift, source/wheel
build and installed-wheel fresh isolation probe passed. Four dirty AUTO001 files
are unchanged and excluded from this increment. Exact implementation commit
`955b08206a4c046720e360196d9884e107ac0400` passed
[CI 38945673491](https://github.com/00-Aryan/python_mastry/actions/runs/38945673491):
**348 passed / 46 isolation skips**, zero failures, 101.89 s, all configured quality,
migration and build checks passed. The separate isolation job skipped. S012 is
**Verified for local scope**; remote/deployed isolation remains unverified. This
separate documentation closeout follows the implementation evidence. S013 is next
ready, not started. API publication still returns 503 until that integration;
question-quality certification is S014. No remaining local S012 blocker.


## S013 local acceptance — 16 October 2026 (UTC)

S013 connects immutable S012 reports to the existing two-transaction publication
transition. Explicit evaluator-policy approval, trusted report/version, complete
passing results, exact content/component pins and age <24 hours are enforced again
under final question/version locks. No reference execution occurs in the API.
Missing approval/evidence or unavailable verification preserves 503. Schema head
remains 0009; no new migration or weakened immutability/worker/isolation controls.
See [decision 0011](../decisions/0011_safe_publication.md).

Local final PostgreSQL/real-isolation suite: **429 passed, zero failures/skips**,
198.55 s. Locked dependencies, Ruff/format (179 files), strict mypy (104 files),
Alembic CLI/no drift, builds, package/source parity and installed mandatory fresh
isolation probe passed. All AUTO001 dirty files are preserved and excluded; .env,
scheduling and operational worker state were not changed. Exact-commit CI is pending.
Local publication is implemented/locally verified; no deployed certification or S014
quality claim. S014 follows after S013 closeout, not started.
