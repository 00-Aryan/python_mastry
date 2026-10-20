# S018 — Counting practice and assessment candidate

DICT-P02 teaches exact-string occurrence counts. DICT-A02 applies signed per-token
changes in sequence, flooring each resulting count at zero before the next event.
Discarded deficits cannot reduce later positive changes. The returned object contains
only final positive counts. Both have the same primary D2 skill and separate reviewed
solution families; this creates no scoring or learner-independence guarantee.

- dict_p02.private.json and dict_a02.private.json are normal admin-create request
  inputs. Their references, tests, rubrics, misconception programs and assistance
  stay in private authoring files, outside ordinary learner DTOs/errors and the wheel.
- s018_references.json adds one D2 skill/pattern and two family definitions. Seed
  existing s015_references.json first to reuse its curriculum; no duplicate D1 or
  new prerequisite graph is created.
- s018_authoring_review.private.md compares all prior learner-visible teaching and
  records precise private contrasts. The repository is public, so source readers
  can inspect these answers. API privacy is a separate tested boundary.
- test_counting_pair.py checks this authored pair; question_pair_checks.py shares
  S017's actual API/CLI quality/publication/learner flow without faking results.

On the supported non-root WSL/Linux host with mandatory isolation controls and a
separate disposable PostgreSQL test database:

```bash
uv sync --locked
RUN_ISOLATION_TESTS=1 TEST_DATABASE_URL='postgresql+psycopg://USER:PASSWORD@127.0.0.1:PORT/mastery_test' \
  uv run pytest tests/integration/test_counting_pair.py tests/integration/test_safe_lookup_pair.py -q -W error
```

Use actual test credentials, not literal placeholders. Test fixtures guard the
operator database and clean random schemas afterward. Without the isolation opt-in,
five S018 cases skip and three static checks run; skipped cases do not certify
execution/publication. With opt-in, missing mandatory controls fail closed.

The normal flow remains stored-admin seed/draft creation, isolated verify-reference,
deliberate policy approval and normal publish. Test-local approval/readiness is not
operator configuration. No importer, migration, operational worker or .env change
is performed. P02 supports practice and A02 assessment; no transfer/review mode or
held-out access control is introduced. Owned help/solution escape records disclosure
permanently; private tests and incorrect programs remain excluded even after escape.

The separate final review is explicitly AI review under the user's authorization,
not human approval or proven independence. Passing real finite bundles does not
complete attempts, grant mastery or certify deployed isolation. See [S018's record](../../docs/roadmap/sprints/S018.md)
for final hashes, decisions, actual results/commits and remaining pilot limitations.
