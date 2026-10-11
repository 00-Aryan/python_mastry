# Python Mastery Backend Project Rules

These instructions preserve Aryan Kumar’s engineering requirements. Place this file at the repository root when implementation begins. Follow the current user’s instructions when they change scope or preferences.

## Read before changing code

Read the Backend Implementation Contract and the relevant feature/decision record. State what is being implemented, its invariants and acceptance tests. Check existing names and patterns before adding alternatives. Do not invent installed tools, package versions, API signatures or successful test results. Verify uncertain behavior against primary documentation or installed code.

## Scope and architecture

Implement one tested increment at a time. Use a modular monolith with explicit API, application, domain and infrastructure boundaries. Thin API routes translate HTTP; application services own use cases and transactions; pure domain functions own learning rules; repositories own persistence. Learner code execution is isolated from the API and database.

Do not build the whole topic catalog or advanced adaptive model in the first increment. Do not create unused empty layers or abstractions. Add each file for a clear implemented responsibility.

## Environment and dependencies

Use Linux or WSL and uv. Keep pyproject.toml, uv.lock and .python-version consistent and commit them. Run through uv run; use uv sync --locked for reproducible checks. Do not add a second independently maintained dependency list. Document setup from a fresh clone and select the WSL .venv interpreter in VS Code.

Never commit .env, credentials or generated virtual environments. Validate settings early and print safe missing-variable errors. Verify compatibility before fixing dependency versions.

## Naming and explanation

Use descriptive snake_case functions, variables and Python files; explicit IDs and duration units; clear enum names. Avoid ambiguous names and catch-all utils modules. Type public boundaries and domain functions. Explain non-obvious invariants, transaction choices and algorithms; avoid comments that simply restate Python syntax.

Each feature’s README or design note must explain file responsibilities, request flow, data relationships and why tests exist. Explain changes in language a learner can follow.

## DRY and maintainability

Keep each business rule in one authoritative location. API, worker and admin paths call the same timer, graph and evidence policies. Extract real shared concepts, not speculative generic frameworks. Prefer focused functions and composition. Do not couple unrelated behavior merely because a few lines look alike.

## Persistence and concurrency

Normalize independent facts and relationships. Use foreign keys, uniqueness and check constraints alongside application validation. Pin attempts to immutable question/policy versions. Use UTC timestamps and explicit integer duration units.

Application services own short transactions; repositories do not commit on their own. Never hold a transaction while waiting for runner/network work. One session per concurrent operation; never share stateful sessions across threads or tasks. Lock attempt mutations and curriculum graph changes consistently. Use idempotency keys, revisions and idempotent worker result application.

Published content and attempt history are not ordinary editable/deletable CRUD. Archive or version content. Ownership derives from authentication, never a request user_id. UUIDs are identifiers, not access control.

## Learning invariants

Server state owns time. Reload, pause, offline behavior and expiry must be defined and tested. Assistance disclosure is permanent evidence. Eligibility/unlocking is distinct from actual content delivery.

Multiple runs and retries of one question do not become multiple Bayesian observations. Exclude incomplete attempts, infrastructure failures, familiar repeats and exposed solutions from new independent evidence. Keep difficulty, mode, policy and retention evidence separate. Store the reason and source IDs for each mastery/recommendation decision.

Do not manually mark mastery through an API. A fake runner cannot grant mastery. Never treat numerical probability as absolute mastery.

## Debugging and errors

Propagate request_id and job/attempt/submission IDs. Use structured safe logs with relevant versions and reason codes. Catch errors at appropriate boundaries; distinguish learner-code errors from infrastructure and application faults. Preserve unexpected stack traces in internal logs while returning safe API responses.

Never silently swallow exceptions or default a failed calculation to success. Never log secrets, full learner code or hidden answers by default. Store immutable submissions for authorized diagnosis. Write a reproduction and regression test when fixing a bug.

## Tests accompany implemented behavior

Every implemented behavior needs meaningful tests in the same increment. Cover happy paths, boundary inputs, invalid states, ownership, conflicts and recovery. Use controlled clocks for timing and real PostgreSQL for transaction/locking behavior. Test numerical examples and evidence exclusions; property-test graph/timer invariants when useful.

Schema migrations require upgrade and data/constraint checks. Workers require duplicate/retry/stale-lease tests. API response tests must prove that private tests and solutions are not disclosed. Execution isolation must be verified before accepting untrusted code.

Do not write superficial tests solely to mirror each code line. A file with declarations can be verified through behavior tests; no empty test placeholders count as coverage. Never report tests as passed unless run. If an environment prevents checks, state exactly which checks remain unverified.

## Change completion

Run relevant pytest tests, Ruff formatting/lint and type checks; run migration and integration checks when persistence changes. Review the final diff and update design/setup notes when behavior changes. Report what changed, why, verification and unresolved limits. Avoid claiming a complete application when only a scaffold or contract exists.

## Roadmap workflow

Before selecting work, read [Master_Roadmap.md](docs/roadmap/Master_Roadmap.md),
[STATUS.md](docs/roadmap/STATUS.md), the selected sprint record and refined contracts.
Inspect actual HEAD and the working tree; credit existing verified work without rebuilding it.
Complete one ready bounded unit and its acceptance checks, then update its record and STATUS
with actual evidence, commit, blockers and next ready unit. Separate implemented, verified
and unverified capabilities; split oversized work rather than waive acceptance criteria.
