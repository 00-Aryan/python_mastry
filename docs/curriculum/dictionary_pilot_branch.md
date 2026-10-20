# Dictionary pilot branch specification — S016

Specification version 1; 17 October 2026 (Asia/Kolkata), with the S017 acceptance
addendum of 20 October 2026 below. This is an authoring plan.
It creates no database facts, published questions, learner restrictions, scoring or
mastery claims. The first branch is **safe dictionary lookup and frequency counting**,
with optional function/loop repair, then ordered selection and applied aggregation.

## Authority and existing implementation

[Roadmap section 4 and S016–S024](../roadmap/Master_Roadmap.md#s016--pilot-branch-specification)
define four areas and a proposed ten-question pilot. The
[backend contract](../Backend_Implementation_Contract.md#10-evidence-eligibility-and-calculations)
defines family novelty, one primary skill and evidence exclusions; refined
[API contracts](../REST_API_Settings_and_Contract.md#s015--first-real-dictionary-question-and-reload-recovery)
define what currently runs. Existing refined behavior takes precedence over broad
planning examples. This document specifies the S016 curriculum choices; later cards
must author, audit and verify their questions before claiming coverage is delivered.

S015 already supplies `DICT-LOOKUP-001`, primary skill `DICT-SAFE-LOOKUP` with UUID
`15000000-0000-0000-0000-000000000011`, curriculum
`15000000-0000-0000-0000-000000000010` and family `DICT-LOOKUP-S015` with UUID
`15000000-0000-0000-0000-000000000031`. Reuse those identities and its tested workflow.
Do not rename/rewrite the immutable published history, duplicate its primary skill
or count a new question code with the same lookup demands as a fresh family.
See [S015 authoring inputs and walkthrough](../../content/dictionaries/README.md).
All other skill/family identities below are design labels, not allocated UUIDs.

## Four observable subskills and rubrics

D1–D4 are local planning labels for the four areas already named in the roadmap.
A later authoring record maps each label to an actual skill UUID. Only D1 currently
has an authored, executed question; D2–D4 are specified, not implemented coverage.

| Label / area | Observable primary criterion | Required contrasting cases for later authoring | Limits of the claim |
|---|---|---|---|
| D1 — Safe lookup | Return a present value, including zero, and distinguish an absent key under an explicit fallback/presence policy. | Present versus absent; zero versus missing; caller-selected fallback; empty mapping and exact key identity. | S015 covers integer values only. Revised S017 A01 adds exactly two dependent lookups across flat maps; no blanket null, arbitrary nested/recursive lookup, mutation, exception or general dictionary claim. |
| D2 — Initialization and count updates | Maintain the correct per-key count as items or declared adjustments are processed. | First occurrence versus repeat; duplicates; empty input; independent keys; stated initialization/update rules. | Count identity and normalization are part of the question contract. Passing this does not establish arbitrary aggregation or iteration mastery. |
| D3 — Ordered selection from counts | Select the qualifying result according to the declared original order and tie/no-result rule, using the required count evidence. | Multiple qualifying candidates; first versus last; no qualifying candidate; ties; explicit character, token or event identity. | Dictionary iteration order alone is not evidence of the required input-order semantics. D2 is supporting knowledge, not an automatic second observation. |
| D4 — Validated record aggregation | Apply declared record validation and grouping/aggregation rules and produce the specified summary. | Valid versus malformed records; skip/reject policy; empty and repeated groups; field/type boundaries; stable tie/output rules where relevant. | A failure cannot automatically diagnose intent, syntax fluency or application skill. Nested/prose semantics, mutation and complexity need separate review. |

Each question version has exactly one primary assessed skill with a private rubric.
For that criterion, authors record the expected observable behavior, contrasting
cases, representative wrong programs and reviewed limits (S017 uses the authorized
AI process below; this is not human approval). Secondary concepts
and prerequisite tags do not automatically receive evidence. Use the existing
normalized mappings/rubric field, not a second scoring schema. A real bundle pass is
finite executable evidence; prose, explanation quality and complexity claims remain
reviewed or explicitly pending. S014's root-type checks do not validate nested prose.

## Repair and prerequisite guidance

Suggested direction is prerequisite → dependent: function arguments/return → D1;
D1 plus iteration/state updates → D2; D2 → D3 and D2 → D4. This is a teaching sequence,
not new stored edges. Before any future insertion, reuse the existing curriculum,
active skill identities, serialized DAG validation and revision checks. Do not add
function/loop UUIDs or duplicate the entire Python catalog in S016.

| Observed difficulty / learner report | Suggested bounded repair | Return and evidence rule |
|---|---|---|
| Function cannot be called as specified, missing return, parameter confusion, or learner asks for function help. | Review parameters, call versus return, and a small return-value exercise. | Resume the owned original task if useful; its exposure/help history remains. A later independent check needs its own eligible family. |
| Processing stops early, repeated items overwrite state, loop body/state update confusion, or learner asks for loop help. | Trace one iteration and state changes, then a short iteration/update exercise. | Return to D2 before adding D3/D4 demands; do not erase prior attempts, grants or timing accommodations. |
| Key/default behavior is the obstacle while iteration works. | Offer D1 lookup practice before additional counting. | The learner can continue the requested task; guidance never locks access. |
| Worker unavailable, resource/infrastructure fault, or unclear incorrect result. | Recover/poll stored results and inspect authorized evidence; ask the learner which concept needs help. | Do not label an infrastructure failure as a language gap, force repair or grant/deny credit from it. |

These are suggestions for a later learner/recommendation flow, not an implemented
automatic diagnosis. One failed test or timing expiry alone cannot establish a gap.
No new repair questions are authored here. Full-solution escape and existing owned
content access remain available under their current policies. Repair cannot reset
irreversible assistance/family exposure or create a new independent observation.

## Coverage matrix

Entries are **planned primary coverage**, except the S015 witness noted below.
A cell saying unallocated is a visible gap, not an implicit pass. Independent here
means a proposed unseen initial assessment; independent transfer and delayed review
are separate evidence roles, not replacements for that initial assessment.

| Skill | Practice | Independent candidate | Transfer | Delayed review |
|---|---|---|---|---|
| D1 | DICT-P01 (S017); S015 is an existing same-demand witness outside the ten-slot pack. | DICT-A01 (S017), only after the family audit below. | Unallocated primary slot; use as support in D3/D4 without automatic D1 credit. | Unallocated in the ten-slot plan; no D1 retention claim. |
| D2 | DICT-P02 (S018). | DICT-A02 (S018), only after the family audit below. | Unallocated primary slot; counting supports DICT-T01/T02 without separate credit. | Eligible target for either S021 holdout, once selected and audited. |
| D3 | DICT-P03 (S019). | Unallocated separate initial-assessment slot; T01 is transfer, not a substitute. | DICT-T01 (S019), if demands justify distinct-family transfer. | Eligible target for either S021 holdout, once selected and audited. |
| D4 | DICT-P04 (S020). | Unallocated separate initial-assessment slot; T02 is transfer, not a substitute. | DICT-T02 (S020), if demands justify distinct-family transfer. | Eligible target for either S021 holdout, once selected and audited. |

The roadmap allocates **4 practice + 2 assessment + 2 transfer + 2 review = 10** slots.
It does not allocate all four evidence roles to every skill. Two review slots cannot
cover three primary skills simultaneously. S021 must select each holdout's **one**
primary target from D2–D4 using available evidence or an explicitly documented pilot
choice; preserve the uncovered skill(s) as gaps. No fabricated weakness or multi-skill
credit can fill the capacity gap. S022/S024 must report actual coverage and unmet
criteria. Any additional questions need a separately authorized later plan change.

### Slot register and family boundaries

These eight codes are from S017–S020, not newly authored questions. “Holdout 1/2” are
slot labels from S021, not invented question codes, UUIDs or release promises.
Family assignment must be justified from actual contracts/reference demands in the
owning card; versioned published facts cannot be retroactively merged or reassigned.

| Planned slot | Owner / primary | Family boundary and acceptance requirement |
|---|---|---|
| DICT-P01 | S017 / D1 | A plain value-with-fallback lookup shares S015's family. Reuse its assets as appropriate while preserving S015's question identity. Renaming keys, function or story does not create novelty. |
| DICT-A01 | S017 / D1 | Must change the essential lookup decisions or data flow beyond all learner-visible P01/S015 material, including every hint and solution. Adding a presence flag alone is insufficient when that prior help teaches membership/branching. Audit actual solution differences and contrasts; cosmetic wrappers retain the familiar family and cannot satisfy unseen-assessment acceptance. |
| DICT-P02 | S018 / D2 | Plain per-item frequency accumulation defines a counting family, separate from single-key lookup. Reworded tokens/characters sharing this essential algorithm stay in that family. |
| DICT-A02 | S018 / D2 | Must require a substantively different count-update decision/state contract, not the same frequency loop over renamed inputs or a different return wrapper. The authoring card must document that change and distinguishing cases; if it cannot, keep it familiar and block the card's unseen-assessment claim. |
| DICT-P03 | S019 / D3 | Establish the declared count-and-original-order selection demands. Specify what constitutes a character/event, tie behavior and absence. Merely reversing or renaming an example is not a new family. |
| DICT-T01 | S019 / D3 | Transfer must require a changed solution demand/data flow beyond P03, with explicit order/tie/identity semantics and reviewed contrasts. Same selection skeleton in a new story remains familiar practice, not verified transfer. |
| DICT-P04 | S020 / D4 | Establish a declared validated-record aggregation contract; exact field/type and malformed-input decisions belong to the authoring card. A new field name alone leaves the family unchanged. |
| DICT-T02 | S020 / D4 | Require a substantive change in validation/grouping/aggregation decisions beyond P04, with contrasts proving the change. Ordinary repetitions cannot be promoted to transfer because their codes start with T. |
| Holdout 1 | S021 / one selected D2, D3 or D4 | Distinct reviewed family from the learner's relevant attempted/assisted sources and from Holdout 2; privately retain source/version/review rationale. Select primary before authoring/publication. |
| Holdout 2 | S021 / one selected D2, D3 or D4 | Same novelty/review requirements, independently audited. Record the two selected targets and any uncovered D2–D4 coverage; do not imply all three were reviewed. |

An authoring novelty audit records actual source question/family/version IDs, primary
skill, essential solution demands and changed decisions, counterexamples, overlap
with known solutions and the reviewer's conclusion. A new UUID is never that audit.
If substantially the same solution suffices, reuse the known family or retain the
familiar/excluded classification; do not claim independent/transfer/review evidence.
Even a justified new family is only a content classification, not runtime eligibility:
learner exposure, assistance, timing, mode/policy, actual outcome and later checkpoint
rules still apply. Repeated submissions do not become multiple observations. Delayed
reviews describe retention separately and require actual elapsed-time observations;
no simulated future success or automatic +3/+10-day mastery credit is inferred.

## Authoring roles versus current runtime capability

Practice, independent, transfer and review are curriculum roles in this specification.
Existing question metadata can describe transfer/delayed_review, but the released
StartAttempt API and pinned pilot policy accept **practice/assessment only**. There
is no released review-task scheduling/release flow. Do not silently treat a practice
attempt as transfer/review evidence, bypass that allowlist or publish holdouts into
the ordinary catalog while claiming guarded review access. S021 must explicitly
resolve its controlled-access requirement against then-available runtime controls;
currently that is a downstream capability gap, not implemented by S016.

No present evaluation automatically completes an attempt or computes eligibility.
The existing S015 witness is assisted practice passing its full pinned bundle,
not initial independent evidence. D3/D4 initial assessments and absent role coverage
remain pending if future competence criteria require them. This specification does
not establish competence levels, mastery, retention, a ten-question release or R0.

## Publication, privacy and operational invariants

All later question assets remain private authoring inputs until their authorized
learner flow: tests, rubrics, references and incorrect programs never enter public
question/list/error responses. Hints/solutions require owned irreversible grants;
misconception programs remain private even after solution escape. This public Git
repository provides no answer secrecy from repository readers. This document adds
no hidden test values, source solutions or learner diagnostics to a public endpoint.

Every authored question still needs S014 contract/reference/misconception validation,
complete ordered assistance and a fresh approved immutable quality-v2 report. S013
re-locks and rechecks exact revision/snapshot/hash before publishing; missing usable
evidence remains 503. Final-lock freshness, archive/reference/admin checks, durable
replays and immutable published assets/submissions remain unchanged. S015's worker-exit
repair preserves owned stored result/history and exact retries; new admission still
requires authenticated ready isolation and fails closed otherwise. No fake adapter
can validate an authored question or grant correctness outside tests.

S016 changes no code, API, database, seed, authoring JSON, worker, runtime profile,
operator approval, .env or scheduling. Existing services own transactions, pure rules
and repositories as documented; no second curriculum service/schema is introduced.

## Missing details and downstream acceptance gates

| Requirement or gap | Resolution / owning card |
|---|---|
| D1–D4 labels lacked explicit definitions. | Defined here from the four roadmap areas; no invented installed skills. D1 reuses its actual S015 identity. |
| Exact A01/A02/T01/T02 contracts and novelty judgments do not exist yet. | Boundary rules above constrain S017–S020. Actual statements, tests, reference/incorrect programs and documented novelty review are required there. S017 uses the user-authorized separate AI review below; later cards retain their own review requirements and no successful audit is inferred. |
| Two holdouts are assigned to a pool of three skills with no exact targets/codes. | Keep two unassigned slots, require explicit primary targets in S021 and retain capacity gaps; do not invent a third review question. |
| The ten-slot plan leaves some primary roles unallocated. | Matrix preserves those gaps. S022/S024 cannot claim all-role/all-skill competence or retention from this pack alone. |
| Runtime transfer/review modes and guarded review release are unavailable. | Preserve allowlists; S021 must record a blocker if its access criterion remains unsupported rather than expose holdouts or fake review completion. |
| Rubric explanation, nested constraints, non-mutation and complexity need review. | Separate reviewed evidence or pending limits, not inference from finite JSON return comparisons. |

These do not prevent documenting the S016 branch specification. They do prevent
claims of later content/runtime completion. No missing or contradictory S016 card
criterion requires a new feature or an expanded pilot count. S017 is the next unit
only after this specification's acceptance/CI closes; it has not started.


## S017 acceptance addendum — 20 October 2026 (Asia/Kolkata)

The user explicitly authorized: “replacing the project's manual human-review
requirement with documented AI review” for this S017 closeout. This supersedes the
manual-review blocker recorded at ebe3b50 for S017; it is **not human approval** and
does not lower novelty, quality, privacy or publication standards. Other cards are
not reviewed or completed by this authorization.

A separate AI reviewer must inspect actual learner-visible P01/S015 statements,
examples, all hints and solutions against A01, the primary D1 rubric and these family
criteria. The current presence-only candidate is not accepted merely because its
output has another field. A changed decision or data-flow dependency must survive
comparison with the fully taught P01 solution. Record the reviewer identity, date,
exact final hashes/source revisions, decision, counterexamples, overlap and limits.
The author cannot replace that separate assessment with their own self-approval.

Revised assets require fresh real isolated quality/publication checks and relevant
regressions. Preserve historical question/family/report facts and exact-snapshot,
approval/freshness and isolation gates. If all criteria pass, S017 may be Verified
for its explicit **local content scope under AI review**; otherwise record a specific
content blocker, without requesting manual review. AI assessment does not prove any
learner's independence, mastery, arbitrary correctness or deployed isolation.


## S018 acceptance addendum — 20 October 2026 (Asia/Kolkata)

For S018, the user explicitly requests the documented AI-review process and separate
assessment of final hash-pinned assets, without an invented manual-review gate.
Apply the S017 process above to the counting pair: a separate AI reviewer inspects
all learner-visible prior material, including every P02 example/hint/solution,
against A02's actual changed update/state contract. Record reviewer/date, hashes,
decision, counterexamples, substantive findings and limits. This is AI review, never
human approval; no novelty standard, publication or isolation control is waived.

P02 is exact-string frequency accumulation. The proposed A02 distinction is signed
per-event count adjustment with immediate zero floor and discarded deficits, rather
than final-total clamping. This is still D2 state updating, not D3 result selection
or D4 malformed-record validation. Final review and real quality/publication checks
must accept actual authored assets before counting this as delivered coverage.
Other pilot coverage/holdout/mode gaps remain unchanged.
