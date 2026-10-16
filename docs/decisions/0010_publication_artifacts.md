# S012 — Trusted local reference verification artifacts

16 October 2026. Scope: the canonical roadmap's S012, following locally verified
B6b/S010a/S011. This does not implement S013's publication integration or S014's
question-quality certification.

## Flow and responsibilities

`mastery-content verify-reference --version-id UUID --expected-revision N --runtime PATH`
is an explicit, one-shot trusted **development-only** command. Configure the existing
DATABASE_URL and DEVELOPMENT_USER_ID locally and run `uv run alembic upgrade head`.
Use a fresh curated runtime built/probed using [the existing setup](../Local_Runner_Setup.md).
Do not use this command in the API process or start an operational evaluation worker.

- `content_cli.py` parses the command, resolves the configured database identity,
  configures safe logging and prints only a bounded report. Non-passing reports
  exit 1; invalid settings/auth/runtime fail with safe errors.
- `application/publication_artifact_service.py` rechecks stored content_admin,
  locks/captures a complete nonarchived draft and revision in a short transaction,
  then releases every lock/connection before execution. It parses the canonical
  immutable bytes, checks bounds, runs references, then rechecks authorization
  and appends the report in a second short transaction. Repositories never commit.
- `domain/publication_artifacts.py` defines canonical bundle hashing and bounded,
  allowlisted results. `content.py` remains the authority for authoring snapshots
  and completeness. Existing local sandbox JSON comparison/protocol and isolation
  controls are reused, with no changes to cancellation, worker authority or leases.
- `infrastructure/database/publication_{models,repository}.py` and migration 0009
  store append-only artifacts and reuse immutable `evaluator_policy_versions`.
  Existing runtime `evaluation_test_bundles` require published, immutable test IDs;
  they cannot represent replaceable draft tests. Artifacts instead retain the exact
  bounded authoring bytes and component hashes, independent of later draft edits.

Each invocation has a new report UUID, not an idempotent job/dispatch. No network
callback or supplied “verification result” can create reports. A failed database
commit leaves no report or partial evaluator-policy insertion; retry is a new run.
A crash before committing leaves no success claim. A lost commit acknowledgement
requires operator lookup of the returned/report ID when available or another run;
S012 does not promise exactly-once reference execution or background recovery.

## Pins, bounds and trust

An artifact stores question-version FK/revision, requesting admin FK, canonical
snapshot bytes and SHA-256, canonical examples/test bundle SHA-256, UTF-8 reference
source SHA-256, verifier identity `local-reference-verifier` / version `reference-v1`,
immutable evaluator-policy FK and UTC completion time. The policy pins protocol 2,
sealed runtime image hash and isolation-profile hash. The v1 verifier admits at most
64 combined examples/tests and a one-MiB snapshot; larger complete drafts receive
VERIFICATION_LIMIT, without executing or storing a report. Authoring's existing
limits remain unchanged. Policy version v1 admits new cases for ten seconds;
a case already admitted retains the existing independently enforced three-second
sandbox lifetime. This is a bounded batch, not a ten-second kill of the supervisor.

The policy's orchestration fields are reused immutable descriptors, not learner
jobs or leases. There is one reference batch, no automated retry; no worker is
provisioned, authenticated or made ready by this command. B6b evaluation authority
and signed learner-result handling are untouched.

Only source, function name and one case's input enter each fresh B6b sandbox.
Expected values, other tests, admin/database credentials and solution explanations
remain outside. Grading is trusted type-aware JSON equality outside the sandbox.
The full solution is private input source, never command interpolation or API output.
The result contains only outcome, checked_cases and total_cases; no exception text,
outputs, individual test identifiers or private values. The artifact's retained
snapshot is private authoring data. No public artifact read endpoint is added.

Outcomes: passed, incorrect, syntax_error, runtime_error, resource_limit or
infrastructure_error. Stop on the first failure. Unavailable startup/controls after
valid runtime discovery produce a non-approving infrastructure_error report; invalid
or absent runtime manifests cannot supply trustworthy pins and produce safe
VERIFICATION_UNAVAILABLE without a report. There is no subprocess fallback. Safe
structured logs retain internal exception frames, excluding exception values/source.

Trust is the existing local operator + application database boundary: reports are
written only by this trusted command under stored admin authorization. The sandbox
cannot reach the database or report API. Reports are not signed cross-host attestations;
a compromised operator/database owner can forge INSERTs, as with other application
facts. S012 does not certify deployed service-to-service provenance. PostgreSQL
rejects report UPDATE/DELETE, invalid snapshot hashes, unbounded/extra result fields,
invalid identities/counts and missing FKs. Existing immutable-policy triggers protect
runtime/evaluator pins. Downgrade refuses to discard report history. A referenced
draft cannot be deleted while reports exist (409 VERSION_REFERENCED); it may still
be edited or archived. The final short transaction follows existing admin → question
→ version lock order to serialize artifact creation against deletion.

## Publication boundary

A report is evidence about exactly those bytes, even if a later edit/archive makes it
stale. It does **not** publish or imply question quality, learner correctness, evidence
eligibility or mastery. The existing API UnavailableReferenceVerifier remains the
default, returning 503 without publication state changes even after a passed artifact.
S013 must authenticate/consume the stored artifact, re-lock and recheck revision,
content hash, report/policy freshness, references and archival status. No CLI switch,
HTTP input, fake test adapter or report UUID alone authorizes publication.

S014 still owns richer contract semantics and weak-suite/representative incorrect
solution checks. No claim that passing two fixtures proves strong tests. Production
login, remote/deployed isolation and cross-host attestation remain unverified.

## Tests and evidence

Unit tests establish canonical input/component hashes, byte/result bounds and
rejection of arbitrary adapters. Real PostgreSQL/isolation tests execute correct,
incorrect, syntax-invalid and runtime-invalid references; inspect exact bytes/pins,
DB immutability/constraints and downgrade refusal; race edits/revoke authorization
between transactions; roll back a post-flush failure then retry; check bounds and
actual CLI output/public 503/no leakage. Missing-control fault injection is labelled
as such; existing B6b actual-control/protocol/resource tests run in the full suite.
Migration tests preserve pre-existing evaluator data from 0008 and compare actual
metadata after upgrade/downgrade/re-upgrade. Exact results live in
[the S012 record](../roadmap/sprints/S012.md).
