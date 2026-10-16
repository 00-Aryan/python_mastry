# S014 — Bounded question-quality verification

17 October 2026 (Asia/Kolkata). Authoritative scope: roadmap S014, contract/example/
reference/representative-incorrect-solution checks; reject broken references and weak
suites; preserve assistance privacy. S012 artifacts and S013 publication concurrency,
required approval/freshness and exact-snapshot gates are prerequisites, reused here.
No pilot question/catalog, operational worker, learning rule or deployment is added.

## Authoring format and responsibilities

Admin DraftContent gains private `incorrect_solutions`, a list of at most eight
`{position, label, source_code}` values. Labels are unique uppercase misconception
codes; positions are unique positive integers and must be contiguous for quality
verification. Drafts may omit the list while being authored. A qualifying report
requires two through eight distinct candidate programs, distinct from the reference.
Human authors select representative misconceptions; labels are not proof that every
possible error is covered. Existing admin create/preview/PATCH support the collection;
PATCH replaces it and uses the same expected_revision and stored content_admin rules.
Public DTOs, owned question reads and assistance responses never inherit this field.

`question_incorrect_solutions` normalizes the programs with version FK, unique
positions/labels, source bounds and the existing published-child immutability trigger.
After publication, INSERT/UPDATE/DELETE and moving between versions are forbidden by
PostgreSQL. All programs belong to the private canonical snapshot, so changing one
changes the content hash; report freshness/revision/exact-byte checks still apply.

`domain/question_quality.py` owns pure signature/root-type/candidate/probe rules and
bounded quality values. AST parsing inspects source; it does not execute it.
`infrastructure/runner/reference_quality.py` orchestrates the existing LocalSandbox
one fresh case at a time and grades JSON outside isolation. The existing separate
PublicationArtifactService owns capture/authorization/transactions and appends the
report and quality evidence together after execution. Repositories never commit.
No database connection/lock is held while running source. No API execution, result
callback, fake runtime adapter or worker-authority/lease/cancellation change.

## Contract and executable checks

- Contract names must be valid supported Python identifiers, excluding keywords and
  the verifier's reserved `__mastery_` prefix. Reference and candidate sources define
  one top-level synchronous function with the exact positional argument names/order;
  positional-only arguments are supported. Decorators/defaults/variadic/keyword-only
  signatures are rejected rather than silently interpreted. Helpers/imports may exist.
- Validate every example/test argument count and declared root JSON type, expected
  return type and existing depth bound. Boolean is not an integer/number. Reference
  returns must also satisfy the root return type and type-aware JSON equality.
  Free-text constraints, nested element/range schemas, explanations and complexity
  claims still require human review; no natural-language requirement is executed.
- Run the reference against every example and public/private test. A broken return,
  exception, resource limit, unsupported signature or invalid authored value cannot
  pass. Malformed reference syntax is an INVALID_CONTRACT quality failure before
  execution; this is a quality report, not classification of a learner submission.
- For `raise_value_error`, replace one argument at a time in the first valid example
  with representative wrong root types. A trusted appended probe function observes
  ValueError inside the sandbox and returns only a boolean. The validated identifier
  is the only interpolation; source remains bounded protocol data, never shell text.
  Expected answers, other tests, credentials and report/lease context never enter it.
  Zero-argument contracts have no root-type invalid inputs. `not_tested` makes no
  invalid-input guarantee. Value/range constraints are not inferred from prose.
- Every incorrect candidate must first match all public examples. Then at least one
  private test must distinguish it by a wrong returned JSON value or runtime error.
  A candidate which also passes every private test rejects the suite as WEAK_SUITE.
  Invalid signatures/syntax or failing public examples reject the candidate set;
  resource/infrastructure errors cannot establish test strength. These checks do not
  claim universal adequacy or protection against deliberately overfitted authors.

Bounds: at most 64 reference examples/tests, at most eight candidates, at most 256
authored-program execution attempts (plus fixed mandatory isolation probes) and
30 seconds of admission across the quality run, including
startup time. Each admitted execution retains B6b's independently enforced three-
second lifetime and all memory/CPU/pids/storage/output/network/privilege controls.
An admitted last case and bounded cleanup may finish after admission closes. All
source/input/output protocol bounds remain enforced. Exhaustion rejects; no fallback.

## Immutable evidence and policy upgrade

The command remains `uv run mastery-content verify-reference --version-id UUID
--expected-revision N --runtime PATH`, development only under stored admin identity.
It now produces `quality-v2` artifacts and an immutable `publication_quality_evidence`
row with reason_code, total_candidates, killed_candidates and executions. Allowed
reasons: PASSED, INVALID_CONTRACT, INVALID_CANDIDATES, REFERENCE_FAILED, WEAK_SUITE,
INFRASTRUCTURE_ERROR, RESOURCE_LIMIT. Counts are bounded; a PASSED row requires all
of at least two candidates killed and a coherent minimum execution count. The
existing result JSON retains its bounded reference-case aggregate and overall
outcome. No candidate label/source, test values or diagnostics appear in the summary.
Infra failures remain infrastructure_error (503 at publication), never content success.

The canonical snapshot now includes the private candidate collection. Its SHA-256
pins candidates alongside tests, reference, hints, solutions and mappings. Retain
separate reference/bundle hashes and exact runtime/profile pins. The evaluator's
immutable policy changes to a 30-second descriptor with namespace
`publication-quality-v2:` and `publication-v2-UUID` version code; identity remains
`local-reference-verifier`. This is not an evaluation worker or learner policy.

Migration 0010 adds normalized candidates/quality evidence and permits both historical
reference-v1 and quality-v2 report rows. It does not UPDATE old reports, hashes,
policies, published receipts or assets. Old canonical bytes need not decode as the
new schema to remain retained audit evidence. Existing publications stay published;
old v1 evidence cannot approve a new publication even if explicitly approved in
configuration. Regenerate quality-v2 evidence and deliberately approve its new policy
ID, then restart/drain the local API as documented in S013. No automatic approval and
no .env modification occurs here. Downgrade refuses to discard candidates, quality
reports or v2 evidence. A history-free downgrade restores the prior verifier constraint.

S013's outside-authoring-transaction report read, final locks, revision/hash/archival/
references/stored-role checks and 24-hour/future-time boundaries remain. A supported,
approved, matching PASSED quality row is now also required. Missing quality evidence
or a legacy/unavailable report yields 503. Mismatched evidence yields 409; failed
quality yields VERIFICATION_FAILED. No older successful report bypasses newer failure.
Replay/rollback behavior is unchanged. Private report data remains inaccessible via
public lists/details/errors and learner identity never authorizes authoring writes.
Full solution disclosure still requires the existing owned-attempt authorized grant;
misconception source remains private even after that grant.

## Verification and limits

Unit tests cover strict JSON root types, signatures, malformed/duplicate/missing
assets, invalid-input probes and all S013 pin/freshness checks. Real PostgreSQL and
isolation tests distinguish good quality, broken reference, weak duplicate-only
private tests, implausible/syntax-invalid candidates, wrong contract and correctly/
incorrectly implemented ValueError policies. Candidate resource exhaustion rejects.
Tests verify old artifact bytes survive upgrade, v1 cannot publish, new asset CRUD/
FK/uniqueness/checks, published/quality immutability and downgrade refusal. An owned-
attempt privacy test covers pre-grant reads, denied other-user solution disclosure,
and explicit authorized solution disclosure without exposing misconception code.
Barrier regression includes private candidate edits while publication is outside locks.

Actual results/commits are in [S014](../roadmap/sprints/S014.md). Controlled transition
fixtures are test-only evidence, not real execution. Full real-isolation/cancellation/
recovery checks remain distinct from hosted CI's skipped isolation tests. Local operator/
database trust remains the boundary; no signed cross-host attestation, production
identity, remote/deployed isolation certification or mastery claim is made.
