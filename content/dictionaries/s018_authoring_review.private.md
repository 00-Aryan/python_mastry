# S018 private authoring audit — frequency and chronological count updates

20 October 2026 (Asia/Kolkata), source authoring revision 1. Admin authoring material,
not a frontend/API asset. This public repository cannot hide answers from source
readers. Runtime privacy is separately tested. This audit is authored by the
implementation assistant; separate reviewer /root/s018_novelty_reviewer provides
the final hash-pinned **AI** assessment in S018's record. No human approval is claimed.

## Roles, identities and prior teaching

Reuse curriculum UUID 15000000-0000-0000-0000-000000000010 from S015. Add only D2,
DICT-COUNT-UPDATES / 18000000-0000-0000-0000-000000000011, and one per-key-count
pattern / 18000000-0000-0000-0000-000000000021. Both questions have exactly one
primary D2 rubric; supporting D1/function/loop knowledge gets no automatic evidence.
No stored prerequisite edges or access restrictions are added.

| Question | Role / family | Actual demands |
|---|---|---|
| DICT-P02 | practice-only / DICT-TOKEN-FREQUENCY, 18000000-0000-0000-0000-000000000031 | Count every exact string occurrence. Initialize a new key and increment it once per event. Input order does not change the result. |
| DICT-A02 | assessment-only candidate / DICT-SATURATING-CHANGES, 18000000-0000-0000-0000-000000000032 | Apply signed adjustments in sequence; floor each resulting per-token count at zero immediately and discard deficits. Return only final positive counts. |

Baseline eb3e530 retains S015 and all S017 source assets. S015/P01 teach membership,
branching, lookup/default and falsey-value care; revised A01 teaches a value-to-next-
key dependency across two maps. P02 adds the ordinary dictionary accumulation loop,
including its complete get-plus-one code in the help ladder. The novelty review
assumes the learner may see **all** of those statements/examples/hints/solutions.

P02 does not teach negative updates, intermediate floors, discarded debt or recovery.
A02 changes the state transition, not merely the tokens, function name, event weights
or returned wrapper. Given the same multiset of signed events, its output may change
with order. Plain frequency counting is commutative and monotone. A final signed sum
followed by a positive filter is insufficient for A02. The core shared concept is
per-key accumulation, so this is a bounded content-family distinction, not disjoint
knowledge or proof that a particular learner is unfamiliar.

## Essential private contrasts and limits of observability

| Events | Expected result | Observable distinction |
|---|---|---|
| x:-3, x:+2 | x:2 | Initial deficit is discarded before the positive event; final-total clamping wrongly returns empty. |
| x:+2, x:-3 | empty | Same events in reverse order have a different result. |
| x:+3, x:-5, x:+4 | x:4 | Overshoot resets the effective count; retaining debt wrongly returns x:2. |
| x:+5, x:-2 | x:3 | A partial decrease does not reset every negative event or ignore it. |
| x:+2, x:-2 | empty | Exact zero is omitted in the returned mapping. |
| y:+5, x:-3, x:+2, y:-1 | y:4, x:2 | Underflow of x cannot erase y. |
| x:0 / x:+3, x:0 | empty / x:3 | A zero update does not create a positive count or erase one. |

Additional cases cover repeated positives, empty event lists, empty/whitespace and
case-sensitive token identity, Unicode, all-negative input and larger exact-zero
recovery. P02 covers repeated/interleaved occurrences, empty input, exact case,
whitespace, empty strings and distinct composed/decomposed Unicode strings.

Internal deletion is not an assessed requirement: retaining zero internally and
filtering the final output can be correct. What matters is flooring every **effective
state** before the next update and omitting zero from the returned object. This is
D2 chronological state updating, not D3 choosing an ordered result or D4 validating
malformed records. Inputs are valid bounded arrays; invalid_input_policy is not_tested.
Nested types/ranges and non-mutation remain prose/reviewed constraints, not a newly
implemented schema validator. References only read inputs, but arbitrary learner
non-mutation is not established by return-value tests.

## Examples, help and representative incorrect programs

P02 public examples show distinct tokens and empty input; its statement and full
help explicitly explain duplicates/increments. A02's public example demonstrates a
partial negative decrease and independent token counts, plus empty input. Both
statements specify their entire rules honestly. No example includes private test
witnesses or reference source. Each candidate below must match every public example
before a private semantic mismatch can establish a kill.

| Question / candidate | Private distinction |
|---|---|
| P02 OVERWRITE_REPEATS | Duplicate tokens must accumulate beyond one. |
| P02 SKIP_EMPTY_TOKEN | Empty string is a real key. |
| P02 LOWERCASE_KEYS | Distinct case-sensitive keys cannot merge. |
| P02 STRIP_WHITESPACE | Leading/trailing whitespace is part of token identity. |
| A02 FINAL_TOTAL_CLAMP | Discarded negative debt cannot reduce later positives. |
| A02 ABSOLUTE_UNDERFLOW | A deficit becomes zero, not its absolute value. |
| A02 KEEP_ZERO_OUTPUT | Returned zero counts must be omitted. |
| A02 GLOBAL_UNDERFLOW_RESET | Underflow affects only its own token. |

Wrong initialization, ignoring negatives or resetting on every negative are already
distinguished by the honest A02 public example; they cannot serve as candidates that
must first pass those examples. The case suite still exercises these rules. Resource
errors, syntax faults and infrastructure failures are not credited as semantic kills.

All five assistance stages exist in order, with pinned 60-second waiting budgets.
P02's full help teaches only ordinary frequency counting; A02's help intentionally
teaches its own recurrence through owned irreversible grants. Such disclosures remain
permanent assistance evidence. Source readers and learners exposed elsewhere to the
same recurrence cannot automatically become unseen merely from this family UUID.
No completion, eligibility, recommendation or mastery calculation is implemented.

## Real verification and publication boundaries

Seed existing references first, then s018_references.json. Create fresh drafts through
normal stored-admin authoring, obtain actual isolated quality-v2 reports, explicitly
approve only the real report policy in test-local API settings, and publish through
the existing fresh exact-snapshot/final-lock gates. Missing approval retains 503.
Broken reference and weak private-suite variants must reject and stay drafts.
No automatic operator population, family reassignment, fake verifier or runtime bypass.

Shared tests/integration/question_pair_checks.py extracts the existing S017 executable
flow. Both pair test modules call the same real quality/publication, privacy, owned
help, immutable receipt/report pins and signed isolated learner-evaluation checks.
Tests use disposable PostgreSQL schemas and bounded provision/once workers. Actual
question version/report IDs are generated and recorded in JUnit and S018, not invented
operator IDs. Source authoring revision 1 is not a database version-number promise.

Final AI assessment and real results are in S018. Finite cases and AI content review
do not establish human approval, empirical learner independence, all-input correctness,
complexity, non-mutation, explanation quality, mastery or deployed isolation. Existing
unallocated pilot roles, two-holdout capacity and unavailable guarded review/transfer
controls remain open. Two D2 questions do not complete the ten-question pack.
