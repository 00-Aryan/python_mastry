# S017 — Safe-lookup practice and assessment candidate

This pair fills only S016's D1 practice/independent-candidate slots. It adds
`DICT-P01` and `DICT-A01`; S015's original question and metadata are unchanged.
Private question inputs and the family/rubric review live beside this note:

- `dict_p01.private.json`: existing admin-create request shape; value-with-fallback
  practice, using the existing D1 skill and S015 family.
- `dict_a01.private.json`: source authoring revision 2, assessment-candidate request;
  fixed alias→name→score lookup using two flat maps and the same D1 skill. Separate
  AI novelty review replaces manual review by explicit user authorization.
- `s017_references.json`: retains the rejected presence proposal's identity and adds a
  distinct alias-chain family; it never repurposes the historical UUID. Seed the existing
  `s015_references.json` first; never seed a second D1 skill.
- `s017_authoring_review.private.md`: private contract/rubric/novelty rationale and
  counterexamples. These source-controlled inputs are not frontend/static assets;
  this public repository cannot guarantee secrecy from repository readers.
- `tests/integration/test_safe_lookup_pair.py`: authoring checks plus real quality,
  publication, privacy, ownership and isolated-evaluation acceptance. It reuses S015's
  test-only process/configuration driver, without substituting auth/verifier/results.

Repeat acceptance from the source checkout on the supported non-root WSL/Linux host:

```bash
uv sync --locked
RUN_ISOLATION_TESTS=1 TEST_DATABASE_URL='postgresql+psycopg://USER:PASSWORD@127.0.0.1:PORT/mastery_test' \
  uv run pytest tests/integration/test_safe_lookup_pair.py -q -W error
```

Use actual disposable test credentials locally, not literal placeholders. The existing
fixture refuses the operator database name and drops random schemas afterward.
Tests run real isolated references and incorrect programs, inspect bounded quality-v2
reports, deliberately approve the real policy in test API settings, then publish
through the current gate. Missing approval, broken references and weak suites reject.
Owned learner requests use real loopback HTTP and separate bounded worker invocations;
no operational worker is enabled and .env/operator configuration is untouched.
Without the isolation opt-in, five real cases skip; the three static authoring checks
alone cannot certify publication or execution. With the opt-in, absent controls fail.

P01 supports practice; A01 supports assessment. These are supported runtime modes,
not automatic learning labels. Both question statements/examples may appear through
the existing public published-question projection; references, hidden tests, rubrics,
incorrect programs and unrevealed help do not. Assessment is not a guarded review
holdout and this unit adds no transfer/review release capability.

To author outside disposable tests later, use existing `seed-references`, admin POSTs
with these request files, isolated `verify-reference`, then deliberate policy review/
approval and ordinary publish. Follow [the quality rules](../../docs/decisions/0012_question_quality.md)
and [publication setup](../../docs/decisions/0011_safe_publication.md). No import,
automatic operator approval or release setup is performed here.

These are fresh-catalog inputs: the revised A01 uses a new family. If a prior A01
was already imported, its question-level family cannot be changed by creating a
version. Do not apply this request to rewrite that identity/history; no operator
migration or import is performed here. Git retains d9aea5e's rejected presence
candidate; source revision 2 is not a database version-number claim.

A real passing result means the pinned bundle matched, not arbitrary correctness,
unaided credit, lifecycle completion or mastery. Existing coverage/holdout/mode gaps
remain in [S016](../../docs/curriculum/dictionary_pilot_branch.md). See
[the S017 verification record](../../docs/roadmap/sprints/S017.md) for actual evidence,
failed/skipped checks, source commits and separate documentation closeout.
