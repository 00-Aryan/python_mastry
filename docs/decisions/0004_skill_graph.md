# Skill storage and prerequisite DAG

Date: 9 October 2026

This increment reuses the existing curricula, skills and question-version skill
mappings. It adds skill create/read/edit/archive, prerequisite add/remove and
whole incoming-set replacement, plus bounded graph and neighborhood reads.
Prerequisite edges always point **prerequisite skill → dependent skill**. They
are recommendation guidance; no learner access restriction or recommendation
calculation is implemented. Published-question reads keep their existing policy.

## Responsibilities and request flow

| File | Responsibility |
|---|---|
| api/routers/skills.py; api/schemas/skills.py | HTTP parsing, input allowlists, status/response translation |
| api/dependencies.py | Existing database-resolved content_admin and service injection |
| api/admin_responses.py | Shared command headers and safe error documentation |
| application/skill_service.py | Transactions, lifecycle rules, revisions, locking and graph mutation |
| application/admin_commands.py | Shared stored-role recheck and durable POST replay, extracted from question storage |
| domain/skill_graph.py | Pure whole-graph DAG validation and meaningful cycle paths |
| domain/skill_records.py | Validated skill values, bounded queries and explicit public records |
| infrastructure/database/skill_repository.py | Skill, mapping and edge queries; never commits |
| infrastructure/database/content_models.py | Existing identities plus normalized edges/revision constraints |
| migrations/versions/0003_skill_graph.py | Reviewed upgrade from question storage; retains existing data |

Mutation requests pass the existing local-origin/identity guards and stored role
check. The service rechecks the stored role in its transaction, locks the user,
then the curriculum, then the affected skill. Every graph-changing operation
uses that curriculum row lock, including skill create/edit/archive and bootstrap
skill insertion. Multi-curriculum reference seeds lock curricula in ascending
UUID order. Each operation owns its session; repositories never commit.

Under the curriculum lock, edge commands check expected_graph_revision, load the
current graph, construct the entire proposed graph, validate it, replace the
incoming edges and increment graph_revision before commit. No transaction or
lock spans external work. Incoming-set PUT validates replacement as a whole;
failed validation or a later flush failure rolls back edges and revision together.
Concurrent inverse additions by different administrators cannot both commit.
A stale graph revision returns 409 STALE_REVISION; retrying the inverse edge at
its new revision returns 409 GRAPH_CYCLE with a cycle path containing skill codes.
The pure validator uses Kahn's algorithm and iterative DFS, O(V + E), without
recursive-stack limits. It accepts disconnected nodes, branching and diamonds.

The PostgreSQL edge table has a composite primary key, a non-self check, and two
composite foreign keys to existing UNIQUE(id, curriculum_id) skill identities.
Downgrade removes edges and the new revision counters; existing question/skill facts
remain. Use forward migrations for retained graph data; tests downgrade disposable
schemas only. Thus duplicates, missing endpoints and cross-curriculum edges are constrained
outside the service too. Incoming/outgoing indexes start with curriculum_id.
DAG and lifecycle policy are service invariants: ad hoc SQL writers must use the
service for graph changes; no trigger claims to enforce arbitrary SQL DAG writes.

## Revisions, identity and archival

Skill IDs, curriculum and code are stable; PATCH changes title/competency only.
Skills have positive revisions, starting at 1. Curriculum graph_revision starts
at 0 after migration and increases on each committed skill or topology change.
It therefore identifies the public graph representation, including node metadata.
Bootstrap insertion increments it per new skill; identical seed replay does not.
Identical prerequisite-set PUT does not increment it. Skill edits check their
own expected_revision and refresh the locked database row, avoiding stale ORM
identity-map state when another writer commits while the lock is being acquired.

Archive is permanent, not physical DELETE. Remove **all incoming and outgoing
edges** first; archival never silently removes edges. Remove editable draft
mappings or archive the mapped questions before archiving the skill. Any mapping
on an available question rejects archival with 409 SKILL_IN_USE. Mappings on
archived questions remain intact, including immutable published mappings and
private rubrics; no published child is edited or deleted. Archived skills cannot
be edited or used in new edges/content. They disappear from active graph/catalog
reads, while detail and include_archived catalog reads preserve the identity.

Question reference validation locks skill rows in sorted UUID order. Archival
holds the skill lock before checking mappings, so concurrent mapping creation
cannot leave available content pointing at a newly archived skill. Question
archival is permanent; a concurrent archival may cause a conservative conflict
that the administrator can retry. No historical attempt/evidence policy is added.

## Public reads and bounds

GET /skills is ordered by (code, UUID), defaults to 20 and allows at most 100
(or a smaller configured MAX_PAGE_SIZE). Its opaque cursor expires after one
day and binds to curriculum_id/include_archived; incompatible or malformed
cursors return 400 INVALID_CURSOR. Unknown query fields return 422.

GET /skills/graph requires curriculum_id and returns graph_revision, nodes and
prerequisite→dependent edges. Register it before /skills/{skill_id}. Without a
center it reads the active curriculum graph. With center_skill_id it returns the
induced neighborhood within depth (1–5), traversing prerequisites, dependents or
both; default depth is 1 and direction is both. Missing/archived/wrong-curriculum
centers return 404. Defaults/maxima are max_nodes=100 (1–100) and max_edges=200
(1–500). Database reads use limit-plus-one checks; neighborhood queries also cap
each frontier and cumulative edges. Oversized reads return 422 GRAPH_READ_LIMIT
with instructions to narrow the neighborhood or increase bounds, never a silently
truncated graph. A shared curriculum lock keeps revision, nodes and edges coherent
across these short read queries. No process-local cache is authoritative.

Graph/skill records select skill metadata only; they never load question tests,
hints, solutions, private rubrics or verifier receipts.

## API refinements and acceptance

POST create/add/archive use existing printable ASCII Idempotency-Key rules,
seven-day durable replay and authorization before replay. Add returns 201 with
its canonical edge Location and graph mutation snapshot. PUT replacement returns
200 with the committed revision and incoming IDs. DELETE edge follows the planned
204 contract, requires expected_graph_revision in the query, and clients reload
the graph after deletion. Archived skill commands require expected_revision and
expected_graph_revision. Self-links, duplicate edges, cycles and archival conflicts
return actionable 409 errors. Missing dependent/curriculum is 404; missing,
archived or cross-curriculum prerequisites are 422 INVALID_SKILL.

The planning contracts left exact neighborhood bounds, archival policy, edge
replacement payload and graph revision effects unspecified. The rules above
resolve them for this increment. Curriculum CRUD/status, bulk file edge imports,
related-topic links, persistent admin audit events and graph caching are deferred.
Incoming-set replacement supplies whole-graph validation without a general importer.
The existing release marker remains B1-foundation; learning capabilities stay empty.

Acceptance tests cover valid chains, branching, shared prerequisites and a 2,500
node chain/cycle; self, direct/indirect cycles; duplicate/missing/cross-curriculum
endpoints and PostgreSQL constraints; CRUD/input/replay/cursors/bounds; revoked or
missing stored admin identity; different-admin inverse-edge and same-revision edit
races; rejected replacement and post-flush rollback; incident-edge and available
question archival restrictions; mapping/archival locking and retained published
history. A test-only injected verifier proves published access stays available
with prerequisites and graph responses do not leak private question assets.
Migration checks upgrade actual 0002 data/mappings, compare metadata, replay and
downgrade/re-upgrade disposable schemas.

**Production publication remains unavailable until the trusted verifier is
implemented.** Injected verifiers remain test-only and prove transitions, not
future verifier correctness. Production authentication/startup remain disabled.
Recommendations, mastery, timers, submissions and execution are outside scope.
Actual verification results are recorded in docs/B2_Verification.md.
