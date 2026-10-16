# S013 — Safe publication from immutable local evidence

16 October 2026 (UTC). The canonical S013 card requires verification outside the
transaction, then re-lock/recheck revision/hash, rejecting changed content,
conflicting publication, failed verification and stale reports. S012 already runs
isolated reference verification separately and stores immutable artifacts. B1 already
provides the two-transaction transition, stored admin authorization, replay and
published-asset database guards. This increment connects those existing pieces.

## Local setup and preserved gate

1. Run migrations with `uv run alembic upgrade head` (head remains 0009; no new DDL).
2. As a stored local content_admin, run the existing separate development command:
   `uv run mastery-content verify-reference --version-id UUID --expected-revision N --runtime PATH`.
   Build/probe the curated runtime first as described in Local_Runner_Setup.md.
3. Inspect the bounded report and its evaluator/runtime policy. Approve that exact
   immutable policy by setting PUBLICATION_EVALUATOR_POLICY_VERSION_ID to the report's
   evaluator_policy_version_id in local API configuration, then restart the API.
4. Use the existing authenticated POST /api/v1/admin/question-versions/{id}/publish
   with expected_revision and Idempotency-Key. No HTTP field can supply proof,
   outcomes or policy approval. No worker is provisioned/enabled by this workflow.

Missing approval defaults to 503 VERIFICATION_UNAVAILABLE. Configuring an arbitrary
UUID does not approve anything: a usable stored report with that exact supported,
immutable policy must exist. Missing report, unavailable/infrastructure report or
unsupported/unapproved evaluator policy also gives safe 503. The .env.example contains
only a commented placeholder; this increment changes no operator .env or running setup.
Production authentication/startup remains disabled. This is verified local publication,
not production release certification or S014 question-quality certification.

## Request flow and responsibilities

`api/dependencies.py` selects UnavailableReferenceVerifier unless approval is configured;
otherwise it supplies StoredReferenceVerifier and the injectable server clock. Thin
routes retain their existing body/response schemas and stored-role/origin guards.
`application/content_service.py` retains the existing short transaction boundaries:

- Authorize/recheck stored admin, check successful POST replay, lock question then
  version, check draft/revision/completeness/references/archival, capture canonical
  bytes and content hash, then release all connections and locks.
- Call the report verifier using an immutable PublicationSnapshot that includes
  question-version ID and revision. It reads bounded evidence outside the authoring
  transaction. It never executes code, imports a runner, waits for a worker or trusts
  request-supplied receipts. S012's actual reference execution precedes this request.
- Start the final AdminCommands transaction, authorize again and check replay, re-lock
  question/version, check draft/revision, canonical hash, completeness, references
  and archival. Recheck the same stored report and freshness using the current clock
  inside these locks. Then publish, increment revision and store its proof UUID/hash/
  verifier version in existing verification_json, atomically with successful replay.

`application/publication_report_verifier.py` coordinates reads and safe errors.
`infrastructure/database/publication_repository.py` selects at most one artifact.
`domain/publication_artifacts.py` owns pure evidence/freshness/policy rules and the
shared S012 evaluator descriptor/ID derivation. The descriptor bytes/UUID derivation
are unchanged from S012; existing immutable reports remain valid inputs. The verifier
protocol explicitly separates outside-transaction verification from final database-only
recheck. No no-op runtime adapter or new execution/publication bypass is added; legacy
synthetic transition fixtures remain exclusively under tests/.

## Evidence validation and resolved contract gaps

Reports are ordered by created_at descending, then UUID descending for deterministic
same-timestamp ordering. Select the latest artifact for this question version, including
failures; do not fall back to an older pass. Missing current-revision evidence must be
regenerated even if content is changed and later restored byte-for-byte.

Require the fixed trusted local verifier identity/version, the approved evaluator-policy
FK, supported protocol 2 configuration, deterministic policy ID/version code, and exact
runtime/profile pins. Validate the report schema and aggregate counts, question-version
ID, revision, canonical snapshot bytes/content SHA-256, examples/test-bundle SHA-256,
reference source SHA-256 and actual bundle size. Only a complete passed result qualifies.
The artifact and evaluator policy are already immutable database facts, including the
private snapshot; the existing stored receipt points back to that retained report.

The original contracts did not specify freshness. S013 resolves it as age >=0 and
strictly <86400 seconds; future timestamps and the exact 24-hour boundary reject with
409 VERIFICATION_STALE. Freshness is checked at the publication decision under locks,
not inferred from client time or the earlier outside-transaction check. A changed
latest report also rejects as stale. Policy approval is fixed configuration for the
API process/request; rotate it by restarting/draining requests, not by mutating live
settings. No dynamic policy revocation subsystem is introduced.

409 VERIFICATION_FAILED means a trusted reference failed. 409 VERIFICATION_MISMATCH
means mismatched bytes/pins/identity/shape. Existing STALE_REVISION,
PUBLISHED_IMMUTABLE, QUESTION_ARCHIVED and reference-validation errors remain. Messages
never include source, test inputs/expected values, hints, outputs or private diagnostics.
Report hashes/IDs and verification_json remain absent from public DTOs/detail/lists.
Admin publish responses retain the existing authorized authoring preview.

## Concurrency, retries and trust

Final locks retain admin → question → version ordering. S012 artifact insertion also
uses this order, so report replacement cannot slip past final validation while those
locks are held. Parent and asset guards protect all published children. Distinct
concurrent publish keys produce one transition and one conflict; the same key/payload
replays the same committed response. Authorize before replay. Changed payload conflicts.
A committed replay remains valid after report expiry: it retrieves the past command,
not a new publication. Failed transitions/commit rollback leave the draft and successful
replay absent; the immutable report survives and can be retried while fresh.

Authenticity inherits S012's trusted local operator/database boundary. The sandbox
cannot write reports or reach credentials; HTTP cannot insert artifacts. Database-owner
compromise is outside that boundary, and these are not signed remote attestations.
No live runner availability is required to consume still-fresh, approved evidence;
missing or unusable evidence cannot be substituted with a fake success. Local isolation
verification remains separate from remote/deployed certification.

## Acceptance checks

Pure tests cover all identity/content pins, supported evaluator configuration and
before/at/after freshness boundaries. Real PostgreSQL tests cover default/configured
503, failed/unavailable reports, mismatches, stale revisions and latest failures,
barrier-controlled edits/private SQL changes/archive/references/role revocation/report
replacement/expiry during verification, concurrent same/distinct keys, rollback and
simulated lost-response replay. One negative-fixture setup initially rejected itself
at S012's policy guard; it was corrected to seed malformed test-only database evidence
explicitly, without weakening production code.

Real isolated passing and incorrect references separately produce S012 reports and
exercise S013 acceptance/rejection. Tests forbid sandbox execution during API handling,
verify the exact published bytes/receipt and public privacy, and preserve existing
PostgreSQL published-child immutability checks. Full cancellation/recovery/isolation
regressions run unchanged. Actual results and tested commit are in
[the S013 record](../roadmap/sprints/S013.md). No S014 or operational changes.
