# S017 private authoring review — D1 safe lookup

19 October 2026 (Asia/Kolkata). This is an admin authoring record, not an API or
frontend asset. It intentionally discusses private test witnesses and incorrect
programs. The repository is public: source readers can inspect these inputs; runtime
privacy means they do not enter ordinary learner DTOs, errors, logs or wheel assets.
This rationale is agent-authored; S016's required human novelty review is recorded
separately in S017. No human acceptance, external study or independent pedagogical
validation is inferred from execution checks.

## Assigned roles, identities and source provenance

| Input / role | Primary skill and family | Source and version relationship |
|---|---|---|
| `dict_p01.private.json`, DICT-P01 / practice only | Existing D1 `DICT-SAFE-LOOKUP`, skill UUID 15000000-0000-0000-0000-000000000011; existing family DICT-LOOKUP-S015, UUID 15000000-0000-0000-0000-000000000031. | Reuses S015's `lookup_score(scores, name, fallback)` teaching assets, with a practice-specific rubric and an extra present-equals-fallback witness. It is a new question identity/code, never a new novelty family. |
| `dict_a01.private.json`, DICT-A01 / assessment only | Same existing D1; new family DICT-LOOKUP-PRESENCE, UUID 17000000-0000-0000-0000-000000000031. | `lookup_entry(scores, name, fallback)` reports membership separately from value. It is the independent-assessment **candidate** allocated by S016, not already eligible independent learner evidence. |

The base curriculum/pattern/skill and original family are defined once in
`s015_references.json`; `s017_references.json` adds only the new family. No duplicate
skill, new curriculum, prerequisite restriction or speculative coverage is added.
Existing S015 source question DICT-LOOKUP-001 and its JSON are unchanged from starting
HEAD fb096ad (S015 delivery 055c692; S016 specification 0873bba). This review and the
new authored inputs are pinned together by the S017 content commit. Actual database
question-version IDs/version 1/report IDs are generated and checked during disposable
acceptance, recorded in JUnit and the sprint record; no operator version IDs are
invented or repinned. Published database content remains the runtime authority.

## Observable rubrics and family audit

P01 asks only for an integer value: use the stored value when the key exists,
otherwise the caller's fallback. It preserves zero and negative scores, exact key
identity and empty input behavior. Its same essential value-with-default algorithm
shares S015's family even though the code/title differs. This is familiar practice
if that family has already been attempted; no new independent observation follows.

A01 must return exactly `{found: boolean, value: integer}`. `found` means key
membership. The private pair `({"equal-score": 5}, "equal-score", 5)` and
`({}, "equal-score", 5)` returns the **same value 5**, but respectively requires
found true and false. A result derived only from P01's value and fallback cannot
recover this missing bit of information. A01 therefore requires an independently
observable membership decision, not a renamed story or a constant wrapper. The
reference uses explicit membership and branches to choose the paired flag/value.

The tasks still share D1 concepts, dictionary access and default selection. A learner
who already understands membership may adapt a prior solution quickly. The family
distinction is the documented change in required decisions and observables, not a
claim of disjoint knowledge, psychometric independence or a guarantee that any actual
learner is unfamiliar. Exposure/history, help, mode, timing, outcome and future
checkpoint policy must still decide eligibility. Assistance-free test fixtures that
submit a reference are controlled grading checks, not unaided human performance.

## Private case and incorrect-program review

| Question | Reference and representative mistake coverage |
|---|---|
| P01 | Two public examples (present positive, missing with fallback zero), then private zero with nonzero fallback, empty mapping/caller fallback, negative score, exact case, Unicode/empty keys and present-equals-fallback. The truthiness-default and ignored-caller-default programs both match examples but fail private distinctions. |
| A01 | Two public examples, then private present/absent collision at equal fallback, zero, negatives, empty mapping, exact case, Unicode and empty keys. Presence inferred from value equality fails the equal-fallback witness; presence inferred from truthiness fails stored zero; truthy value selection fails zero with a nonzero fallback. All three programs must match every public example before being killed privately. |

Expected A01 `found` fields are actual JSON booleans, never 0/1; `value` fields are
integers. The real learner-evaluation check separately rejects an integer presence
flag using the existing type-aware JSON comparison. Exact object comparison rejects
missing/extra keys on exercised cases. No executable expressions or pickle are used.
Both contracts accept valid integer-valued mappings and choose `not_tested` for invalid
inputs; no unsupported nested-schema validator is implied. Statement, examples,
private expected values, hints and references agree on zero, missing and equal-value
semantics. Submitted source is never executed in the API.

All five hint stages are present, ordered and use the pinned 60-second waiting budget:
direction → pattern → pseudocode → partial code → explicit full-solution escape.
Direction does not reveal later stages. Full solution is available only through an
owned confirmed grant; incorrect programs/private tests remain excluded even then.
No links to S018, transfer, delayed review or held-out assets are created.

## Verification and bounds

Use existing admin create/preview, isolated `mastery-content verify-reference` and
normal publish routes; no importer or seed creates a published question. Both real
reports must pass quality-v2 with every candidate killed; missing policy approval
stays 503. Publication rechecks fresh approved immutable evidence, revision and exact
snapshot under final locks. Negative real runs replace the reference with a wrong
return or weaken private cases to duplicate a public example; both must stay drafts
with VERIFICATION_FAILED. Mutants are not credited for syntax/resource/infra errors.

The API/CLI acceptance driver uses production auth, clocks, services, sandbox and
signed worker results, with test-only disposable-schema/settings wiring from S015.
Worker calls are bounded `provision`/`once`, never an operational serve loop. Approval
and readiness are test-local, not .env/operator changes. The real pair walkthrough
checks role allowlists, canonical immutable report pins, ownership, future-stage/
private-asset exclusions, distinct/familiar family facts, submission snapshots and
stored results/replays after readiness withdrawal and API restart.

Finite cases do not prove arbitrary-input correctness, non-mutation, nested/prose
constraints, explanation/complexity quality, mastery or deployed isolation. The
references were reviewed for read-only dictionary operations; arbitrary learner
non-mutation is not certified by returned-value tests. Quality-v2 still enforces its
execution/resource/admission bounds and preserves infrastructure versus code failure.
The audit is an authored design rationale plus actual checks, not an expert human
study. Actual run results/commits are in [S017](../../docs/roadmap/sprints/S017.md).

S016's unallocated D1 review/D1–D2 transfer/D3–D4 initial roles, two-holdout capacity
and unavailable guarded transfer/review flows remain open. Two authored D1 questions
do not close those gaps, complete the pilot, grant mastery or certify a deployment.
