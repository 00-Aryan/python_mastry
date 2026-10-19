# S017 private authoring review — D1 safe lookup, revision 2

20 October 2026 (Asia/Kolkata). Private admin authoring material, not a frontend or
API asset. Exact private witnesses, misconception programs and answers remain in
these authoring inputs. The repository is public, so source readers can inspect
them; runtime API privacy is distinct from repository secrecy.

The user authorized documented **AI review** in place of S017's manual human-review
requirement. This rationale is authored by the implementation assistant; a separate
AI reviewer assesses the final hashes in S017's record. Neither is human approval.

## Source identities and superseded candidate

- Original delivery d9aea5e, documentation 0e07d33 and initial AI assessment ebe3b50
  remain historical references. Git retains their exact old inputs and audit.
- P01 is unchanged, practice-only, primary D1 skill UUID
  `15000000-0000-0000-0000-000000000011`, existing curriculum/pattern and family
  `DICT-LOOKUP-S015` / `15000000-0000-0000-0000-000000000031`. It retains S015's
  value-with-fallback demands, not a new independent family.
- The original A01 presence/value wrapper is **rejected for novelty after P01 help**.
  P01/S015 hint stages 2–4 already teach its membership/branch solution. An extra
  output bit and equal-fallback witness cannot establish the required changed
  solution demand. Preserve the original proposed presence-family UUID
  `17000000-0000-0000-0000-000000000031` and metadata; do not reuse it for the revision.
- A01 source authoring **revision 2** uses the same D1 primary skill and supported
  assessment mode, with the new `DICT-LOOKUP-ALIAS-CHAIN` family UUID
  `17000000-0000-0000-0000-000000000032`. It requires fixed two-hop lookup in two
  flat maps, not counting, ordering, aggregation or arbitrary nested lookup.

`source authoring revision 2` is a repository revision label, not an invented
persisted question version. Acceptance creates fresh disposable questions and real
version-1 reports/publications; actual generated IDs/hashes are recorded separately.
Existing immutable question versions/reports/family exposure are never rewritten.
Question.family_id belongs to the question identity: an operator who already imported
the rejected A01 must not apply this request as a family-changing version of that
identity. This unit supplies fresh-catalog inputs only, not an importer, reassignment
or operator migration. Reusing an existing code fails normally; a future authorized
identity transition would need its own plan. No operator content is populated here.

## Review of all prior learner-visible teaching

P01 and S015 statements/examples teach choosing a stored score or caller fallback.
Their full help ladder additionally teaches key membership, branching and direct
indexing; the reference uses dict.get. Those are shared supporting lookup concepts.
Review assumes the learner could have seen **every** P01 hint and solution, rather
than treating the short canonical reference as the only exposure.

A01 requires `lookup_alias_score(aliases, scores, alias, fallback)` to use the
retrieved alias value as the next map's key. P01's stored value terminates the
lookup; A01's first value is an intermediate name needed before the score can be
selected. Renaming the original key or wrapping the P01 result cannot create that
data dependency. The new rubric observes correct key flow and both missing-link
boundaries, not the addition of an output field. Output remains an integer.

Concrete private contrasts (retained in the JSON test bundle):

| Decision | Witness and expected result | Why P01-only adaptation fails |
|---|---|---|
| Resolved key wins over original | aliases short→Ada; scores short→99 and Ada→8; query short, fallback −1 → 8 | Reading the caller alias directly in scores selects 99. |
| Missing alias stops | empty aliases; scores short→99; query short, fallback −1 → −1 | Treating an unresolved alias as its own name selects 99. |
| Missing target stops | aliases short→Ada; scores short→99 only; query short, fallback −1 → −1 | Alias presence alone does not establish score presence, nor permit retrying the old key. |
| Empty target remains valid | aliases short→empty string; scores empty string→0 and short→99; fallback 7 → 0 | Truthiness checks erase a valid intermediate key or score. |
| Exactly one alias mapping | aliases start→middle and middle→end; scores middle→4 and end→9; query start, fallback −1 → 4 | Following another alias produces 9; the wrong program terminates normally, so its kill is semantic. |
| Same name is valid | aliases same→same; scores same→5; fallback −3 → 5 | Returning fallback cannot accidentally satisfy the expected result. |

Additional cases cover zero/negative scores, empty maps/query keys, exact alias and
resolved-name case, Unicode identity, a caller-selected negative fallback and a
score equal to fallback. Inputs are valid flat maps; invalid input policy remains
not_tested. No unsupported nested-schema validator, null policy, loop/recursion
competence or multi-skill evidence is implied.

## Examples, help and misconceptions

Public example 1 demonstrates an actual renamed alias ace→Ada with score 8. Example
2 demonstrates an absent alias returning fallback 0. They describe the contract
honestly without source code, private expected values or future-stage help. Each
private misconception below must first match both public examples.

| Incorrect program label | Mistake | Private semantic distinction |
|---|---|---|
| UNRESOLVED_ALIAS_IS_KEY | Uses the original alias as a name when no mapping exists. | Missing alias with an original-key score. |
| EMPTY_TARGET_IS_MISSING | Treats an empty resolved string as absence. | A valid empty-string target has score zero and nonzero fallback. |
| SCORE_TRUTHINESS | Treats a stored zero score as absence. | Stored zero with fallback 7. |
| ORIGINAL_KEY_PRIORITY | Reads scores under the original alias before resolving it. | Both original and resolved score keys exist and disagree. |
| EXTRA_ALIAS_HOP | Follows one additional alias mapping. | Terminating start→middle→end contrast above. |

All five stages retain ordered owned disclosure and 60-second wait budgets.
A01's later help intentionally explains the dependency and full reference; those
are assisted/exposed attempts. P01 help does not supply the two-map dependency,
but prior experience elsewhere with alias chains may. No actual learner history
or unseen eligibility is inferred from a new family UUID. Private tests/rubrics/
incorrect programs remain excluded from public DTOs, errors and even full-solution
escape. Only the owned pinned reference may be revealed by that escape.

## Verification and limits

Use actual admin draft creation, quality-v2 isolated verification, explicit test-local
policy approval and ordinary publish with all existing final-lock freshness/hash/
revision checks. Both questions need fresh reports for this revision's acceptance;
old presence reports cannot certify the changed content. Broken references and weak
suites must reject and remain drafts. Reuse real learner/worker tests for incorrect
and correct results, immutable receipts/pins, ownership/privacy and durable replay
once bounded workers exit. No fake verifier, test result callback or API execution.

The separate AI reviewer rejected the first candidate and requested stronger final
contrasts in its interim two-hop review. The final assessment, exact hashes and real
run results are recorded in S017. This audit is not a human endorsement, empirical
study or proof of psychometric independence. Both tasks retain D1 overlap. Future
eligibility still depends on actual familiarity/help, policy, mode, timing and outcome.

Finite return-value checks do not prove all-input correctness, learner non-mutation,
complexity, explanation quality, arbitrary nested lookup, human competence or mastery.
References use read-only dictionary operations; general learner non-mutation remains
uncertified. Unallocated pilot coverage, two-holdout capacity and unavailable guarded
transfer/review flows remain open. No remote/deployed isolation certification follows.
