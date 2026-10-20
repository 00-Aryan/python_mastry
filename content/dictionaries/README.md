# First executable dictionary question (S015)

The S015 inputs below provide the original executable witness.
[S017 adds the two D1 pair inputs](s017_pair.md), and
[S018 adds the D2 counting pair](s018_pair.md). This is still an incomplete pilot
authoring directory, not an import tool or a complete ten-question catalog.
[S016's branch specification](../../docs/curriculum/dictionary_pilot_branch.md) maps
the later ten-slot plan and its coverage gaps; it preserves these S015 identities.
`DICT-LOOKUP-001` asks for an integer dictionary lookup with a caller-selected fallback.
A present zero must remain zero; only an absent key uses the fallback. The primary
skill and rubric assess that distinction. No iteration/counting/transfer skill is
credited. Empty dictionaries, zero, negative values, case-sensitive, Unicode and empty
keys have declared examples or private edge cases. These finite checks do not prove
arbitrary-input correctness, non-mutation or complexity.

- `s015_references.json` seeds one curriculum, skill, pattern and question family
  using existing `mastery-content seed-references`. IDs are stable authoring references.
- `s015_lookup.private.json` is the existing POST `/api/v1/admin/questions` request
  body: public statement/contract/examples plus private tests, five assistance stages,
  reference and two misconception programs. It is admin/worker input, never a frontend
  asset or static public response. This repository is public, so its Git contents are
  visible: API privacy does not promise answer secrecy from repository readers.
- `tests/integration/test_first_question.py` drives stored-role authentication over
  actual loopback HTTP, real reference verification/publication and separate bounded
  worker processes against randomly named disposable PostgreSQL schemas.
- `tests/integration/first_question_process.py` is test-only process wiring. It sets
  development settings without reading .env and supplies the disposable schema's
  search_path. It invokes the installed application/CLI code; it does not replace
  authentication, clocks, verifiers, adapters, isolation or result application.

## Repeat the bounded acceptance walkthrough

From the source checkout on a capable non-root Linux/WSL host, install locked
requirements and satisfy the [mandatory runner controls](../../docs/Local_Runner_Setup.md).
Supply a separate disposable PostgreSQL database ending in `_test`:

```bash
uv sync --locked
RUN_ISOLATION_TESTS=1 TEST_DATABASE_URL='postgresql+psycopg://USER:PASSWORD@127.0.0.1:PORT/mastery_test' \
  uv run pytest tests/integration/test_first_question.py -q -W error
```

Use real test credentials locally, not the literal placeholders. The fixture rejects
the configured application database name. It migrates a random schema and drops that
schema afterward. The API is loopback-only. Identities, approved report policy and
worker credentials exist only in that schema/test directory. Every worker invocation
is `provision` or `once`, never `serve`; processes stop, readiness is withdrawn and
sandbox units are cleaned up. It neither modifies .env nor enables an operational
worker. Without the isolation opt-in, three real scenarios skip; the authoring check
alone is not S015 acceptance. Missing mandatory controls with opt-in fail the run.

The walkthrough deliberately exercises:

1. Seed separate admin/learner identities and references with the existing CLI; create
   the draft through HTTP. Publication without approval returns 503 and stays draft.
2. Run `mastery-content verify-reference` separately under real isolation. Inspect
   passing quality-v2 evidence (both plausible misconceptions killed), then explicitly
   approve that exact policy in the **test API's** settings and publish. No client
   proof or automatic approval is added to the product. Publication retry recovers
   the original result. Negative scenarios reject broken references and weak suites.
3. Start an owned practice attempt, select 600 seconds, pause, stop the API process,
   recreate it and read the same paused duration/pins. Retry start/pause and resume
   using server revisions. This proves database reload, not browser draft persistence.
4. Submit the truthiness mistake to the public-only bundle: it passes public checks.
   Submit it to the assessment bundle: a real signed worker result is incorrect.
   Public-run success therefore cannot stand in for full-bundle success. Receipt
   status remains received/not_requested; status comes from the evaluation resource.
5. Grant only the requested direction, retry the same grant and reject a distinct
   immediate next-stage request. Pending assessments deny new help. Submit a corrected
   implementation and get a real passing full-bundle result. Preserve earlier
   assistance-free receipt snapshots; the corrected receipt records the hint grant.
6. Restart the API again and recover evaluation/grant history and old request retries,
   even with worker readiness withdrawn. Another learner receives 404 for owned
   resources; learner admin writes receive 403. Verify exact publication bytes,
   source/question/policy pins and authenticated immutable provenance privately.

Under the existing refined contract, a passing evaluation does **not** set attempt
lifecycle to completed or award credit/mastery. The demonstrated result is assisted
practice passing its pinned test bundle; the attempt remains active. The source is
not a browser workspace, and no R0, deployed authentication/isolation or universal
semantic completeness is claimed. Later checkpoint/browser work retains its own gates.

To author this question outside disposable acceptance later, seed these references
and POST the request file through the normal admin API (for example, curl
`--data-binary @content/dictionaries/s015_lookup.private.json`). Review the actual
report and deliberately approve its immutable policy as specified by
[publication setup](../../docs/decisions/0011_safe_publication.md) and
[quality-v2 rules](../../docs/decisions/0012_question_quality.md). The authoring files
never bypass those gates. Operational setup is not performed by S015's tests.

Actual tested commits, CI, passed/skipped checks and limits are in
[the S015 record](../../docs/roadmap/sprints/S015.md).
