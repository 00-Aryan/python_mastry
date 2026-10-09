# B1 question storage

Date: 9 October 2026

## Implemented scope and invariants

This increment stores question identities, editable drafts and immutable published
versions. It implements draft create/read/update/delete, new-version creation,
publication gating, question archival and public catalog reads. It also supplies
the minimum local identity/role and reference-catalog setup needed to use those
operations. There is no DAG, timer, submission, code execution or learning model.
The health/public-configuration release marker remains `B1-foundation` while B1
is delivered in increments; learning capabilities and attempt modes remain empty.

The invariants are:

- An identity has a unique code and a required novelty-family foreign key.
  Code/family are immutable. Versions have unique positive numbers per question.
  The locked question's `last_version_number` allocates numbers monotonically,
  including after deleting a draft; numbers are never reused.
- Draft edits require `expected_revision`. Concurrent edits at the same revision
  produce one success and one `409 STALE_REVISION`. A published version cannot
  become a draft, be edited or be deleted.
- PostgreSQL protects the parent **and every version-owned asset table** against
  insert/update/delete after publication. Child triggers lock the owning version
  before checking status, including insertions into empty collections. A child
  cannot be moved between versions. Links are owned by their source version;
  creating a new draft link to an existing published target remains possible.
- Publication checks completeness and valid active references, serializes all
  content (including private assets) to canonical JSON **bytes**, and releases
  the transaction before invoking a verifier. A second transaction reacquires
  locks and checks draft status, the expected revision, content hash, references
  and archival state before committing publication and its verification receipt.
- The normal verifier always raises `VERIFICATION_UNAVAILABLE`. Valid complete
  drafts receive a safe `503` and remain unchanged, without a successful
  idempotency record. Invalid/incomplete drafts receive documented conflicts
  before verification. There is no request setting, CLI switch or seed command
  that pretends verification succeeded.
- Public queries select an explicit allowlist. They do not load test cases,
  assistance, solutions, private rubrics or verification receipts. Lists batch
  public projections rather than querying every question separately.
- Archive is permanent. Public detail/version/list queries hide archived
  questions. Admin preview preserves their history. New drafts, draft edits and
  publication are denied after archive; an unreferenced draft can still be deleted.

## Responsibilities and request flow

| File | Responsibility |
|---|---|
| domain/content.py | Authoring value validation, publication completeness and canonical content snapshot/hash |
| domain/content_records.py | Explicit admin/public snapshots and catalog query values |
| domain/identity.py | Server-derived principal and content-admin policy |
| domain/content_seed.py | Validated reference-catalog inputs |
| api/schemas/questions.py | HTTP create, patch and revision input allowlists |
| api/dependencies.py | Local request guards, server principal and service injection |
| api/routers/questions.py | Parse HTTP, invoke services, serialize statuses/headers |
| application/content_service.py | Authorization recheck, transactions, revision checks, lifecycle transitions and durable POST replay |
| application/catalog_service.py | Read transactions and filter-bound cursor handling |
| application/publication_verification.py | Trusted-verifier protocol and the unavailable runtime adapter |
| application/identity_service.py | Short transaction to resolve the configured local principal |
| application/content_seed_service.py | Atomic local identity/reference setup |
| infrastructure/database/content_models.py | ORM facts and PostgreSQL constraints |
| infrastructure/database/content_repository.py | Admin content queries, reference checks and flushes |
| infrastructure/database/catalog_repository.py | Public projections; no private relationship loading |
| infrastructure/database/identity_repository.py | Active user and role lookup |
| content_cli.py | CLI parsing and safe setup failures |
| migrations/versions/0002_question_storage.py | Reviewed DDL, partial indexes and immutability triggers |

A write flows through request/body guards → server principal and stored admin-role
check → application transaction → stored-role recheck → question/version lock →
revision/reference/domain validation → repository mutation/flush → commit → safe
DTO. The service creates one session per operation. Repositories never commit.
Mutations lock the local user, then question, then version. The user lock also
serializes successful POST/idempotency insertion for that principal. No lock or
session is held during external verification. Ordinary database connection/pool
outages become a safe 503; unexpected faults retain safe internal exception frames
and return 500 without SQL, private values or traceback content.

## Data relationships and database guarantees

`users` and `user_roles` store local identity and explicit role assignments.
`curricula` own `skills`; `patterns` and `question_families` are independent
reference facts. `questions` reference families and own `question_versions`.
Version-mode, version-skill and version-pattern tables normalize the many-valued
relationships. Examples, tests, assistance steps, solutions and version links
have their own tables. JSONB is limited to the function contract, JSON test/example
values, rubrics, verification receipts and idempotent response snapshots.

Foreign keys restrict removal of referenced facts. Unique constraints protect
question codes, reference codes, per-question version numbers, ordered positions
and mapping pairs. A partial unique index permits at most one primary skill per
version; publication requires exactly one. Check constraints enforce known modes,
visibility, assertion/assistance kinds, positive durations/positions/counters,
non-self links and consistent draft/published timestamps/verification fields.
The active public version is the highest published number of an available
question, with an index for that lookup.

Revision `0002_question_storage` upgrades the existing `0001_database_baseline`.
It wires model metadata into Alembic for future reviewed autogeneration. Migration
SQL is independent of importing live ORM table definitions. Downgrade drops this
increment's content and identity tables; use forward migrations for retained data.
Tests downgrade only disposable schemas. Runtime startup never runs migrations.

## Authorization and local setup

`mastery-content seed-identity` takes an explicit UUID, display name and role(s).
It seeds those database grants; no HTTP role-grant endpoint exists. Set
`DEVELOPMENT_USER_ID` to that UUID. Missing configuration, missing users and
disabled users return 401. A stored principal without `content_admin` returns 403.
Services recheck the stored role before mutation and before replaying successful
commands. Request user IDs or role headers cannot choose the principal or grant
privileges.

Configured development identity requires loopback bind/host/origin settings.
Requests must originate from a loopback peer; unsafe browser requests also pass
origin/fetch-site checks. TestClient peers are permitted only in `APP_ENV=test`.
Production and session-auth startup remain rejected. This is the documented
single-operator local mode; deployed login, sessions and CSRF are future work.

`mastery-content seed-references FILE` accepts explicitly supplied curricula,
skills, patterns and families. It requires the configured stored admin identity,
validates the whole input and commits atomically. Repeating an identical seed is
safe; changed existing records and uniqueness/FK conflicts fail. This supplies
question references without broadening this increment into skill CRUD or a DAG.
No sample question pack is automatically installed.

## Contract refinements and resolved ambiguities

The planning contracts do not give exact content enums or an authoring format for
ordered JSON function calls. This increment makes the following narrow choices:

- Difficulty: `easy`, `medium`, `hard`. `assessment_role` uses `practice`,
  `assessment`, `transfer`, `delayed_review`; that role must occur in supported
  modes when publishing. These describe content suitability, not implemented
  attempt capabilities.
- Function inputs are ordered JSON argument lists; contract argument entries
  contain `name` and `type`, and output is a type specification. Supported JSON
  types are integer, number, string, boolean, array, object and null. Invalid-input
  policy is `not_tested` or `raise_value_error`. Rich nested type constraints and
  executable interpretation belong with a trusted verifier.
- Test comparison currently allows only declarative `equals`, never executable
  expressions. Visibility is `public`/`private`; publication requires private tests.
- Example, test and assistance positions start at one and must be contiguous at
  publication. Assistance kinds increase through directional/pattern/pseudocode/
  partial_code/full_solution and end with full_solution. Drafts can be incomplete.
- Publication requires nonblank solution assets, examples, tests, assistance,
  coherent supported modes and exactly one primary skill. Links target another
  available published version and use variation/transfer/review.
- PATCH is partial at the top level. Supplied collections replace that whole
  collection. Only contract and solution accept explicit null; omission preserves
  values. DELETE supplies `expected_revision` as a positive query parameter.
  Archive uses the separate `question_revision` shown in admin snapshots.
- Catalog ordering is ascending question `created_at`, then UUID. Cursors expire
  after one day and bind to difficulty/track/skill/curriculum filters. Unknown
  filters are rejected. Pagination defaults to 20 and is bounded by MAX_PAGE_SIZE.
- State-changing POSTs require printable ASCII Idempotency-Key values (1–128).
  Successful results persist for seven days, scoped to principal and method/path;
  identical replay returns original body/status/Location and Idempotency-Replayed.
  Changed payload returns 409. Authorization precedes replay; failed commands do
  not persist a successful result.

The user explicitly resolved the publication/code-execution conflict: **reject
publication until a trusted verifier is available; use a test-only injected
verifier to exercise transition logic**. Question storage can be complete while
production publication remains unavailable. The injected verifier validates the
transition logic; it does not validate any future verifier, execute reference
solutions, produce learner evidence or certify correctness. The production
startup guard also remains in place.

## Acceptance checks and their purpose

- Real PostgreSQL migration upgrade from baseline, replay, metadata/DDL agreement,
  downgrade/re-upgrade and constraint failures establish actual database behavior.
- API CRUD tests cover invalid/unknown input, revision conflicts, replacement of
  normalized children, draft deletion, non-reused version numbers, explicit
  archive, successful command replay and incompatible keys.
- Direct SQL update/delete/insert tests cover the published parent and every
  owned table, proving immutability is enforced beyond the application service.
- Two real concurrent requests at one revision prove one 200 and one documented
  409. Publication tests pause verification and edit revision, private content or
  archival state before resuming, proving revalidation and transaction release.
- Unavailable and mismatched verification leave the draft unpublished. Tests use
  the actual default dependency for the 503 path; successful test verifiers are
  defined only under tests/.
- Authorization tests remove stored roles, disable/remove configured identity and
  spoof user/role headers. Production/local-network settings and unsafe origins
  are rejected. Replay does not bypass revoked authorization.
- Public detail/version/list/error tests use private-content sentinels and inspect
  executed catalog SQL to establish absence of private queries and bounded batched
  loading. API response allowlists exclude private relationships altogether.
- Transaction and seed tests prove failed writes leave no partial content or false
  idempotent success. CLI checks exercise actual parsing/setup and safe errors.

Actual results are recorded in `docs/B1_Verification.md` after the final checks.
