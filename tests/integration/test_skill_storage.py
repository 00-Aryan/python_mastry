"""Real PostgreSQL CRUD, DAG serialization, archival and migration acceptance."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from fastapi.testclient import TestClient
from sqlalchemy import Connection, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from mastery_backend.application.content_seed_service import seed_development_identity
from mastery_backend.application.skill_service import SkillService
from mastery_backend.domain.content import ContentError
from mastery_backend.domain.identity import Principal
from mastery_backend.domain.publication_artifacts import PublicationSnapshot
from mastery_backend.infrastructure.database import content_models as models
from mastery_backend.infrastructure.database.skill_repository import SkillRepository

CURRICULUM = "00000000-0000-0000-0000-000000000010"
ADMIN = UUID(int=1)


def graph(client: TestClient, **query: object) -> dict:
    response = client.get("/api/v1/skills/graph", params={"curriculum_id": CURRICULUM, **query})
    assert response.status_code == 200, response.text
    return response.json()


def create(client: TestClient, code: str) -> str:
    response = client.post(
        "/api/v1/admin/skills",
        headers={"Idempotency-Key": code},
        json={
            "curriculum_id": CURRICULUM,
            "code": code,
            "title": code,
            "competency": "Observable behavior",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def add(client: TestClient, prerequisite: str, dependent: str, *, revision: int | None = None):
    if revision is None:
        revision = graph(client)["graph_revision"]
    return client.post(
        f"/api/v1/admin/skills/{dependent}/prerequisites",
        headers={"Idempotency-Key": str(uuid4())},
        json={"prerequisite_skill_id": prerequisite, "expected_graph_revision": revision},
    )


def test_skill_crud_and_bound_catalog(storage_client: TestClient) -> None:
    client = storage_client
    before = graph(client)["graph_revision"]
    a = create(client, "AA")
    assert graph(client)["graph_revision"] == before + 1
    body = client.get(f"/api/v1/skills/{a}").json()
    assert body["revision"] == 1
    replay = client.post(
        "/api/v1/admin/skills",
        headers={"Idempotency-Key": "AA"},
        json={
            "curriculum_id": CURRICULUM,
            "code": "AA",
            "title": "AA",
            "competency": "Observable behavior",
        },
    )
    assert replay.status_code == 201 and replay.headers["Idempotency-Replayed"] == "true"
    assert replay.json() == body
    assert graph(client)["graph_revision"] == before + 1
    patch = {"expected_revision": 1, "title": "Updated"}
    response = client.patch(f"/api/v1/admin/skills/{a}", json=patch)
    assert response.status_code == 200 and response.json()["revision"] == 2
    assert client.patch(f"/api/v1/admin/skills/{a}", json=patch).status_code == 409
    for invalid in [
        {"expected_revision": 2},
        {"expected_revision": 2, "title": None},
        {"expected_revision": 2, "title": "   "},
        {"expected_revision": 2, "code": "CHANGE"},
    ]:
        assert client.patch(f"/api/v1/admin/skills/{a}", json=invalid).status_code == 422
    page = client.get("/api/v1/skills", params={"limit": 1, "curriculum_id": CURRICULUM}).json()
    assert len(page["items"]) == 1 and page["next_cursor"]
    next_page = client.get(
        "/api/v1/skills",
        params={"limit": 1, "curriculum_id": CURRICULUM, "cursor": page["next_cursor"]},
    ).json()
    assert next_page["items"][0]["id"] != page["items"][0]["id"]
    for query in [{"cursor": "invalid"}, {"cursor": page["next_cursor"], "include_archived": True}]:
        assert client.get("/api/v1/skills", params=query).status_code == 400
    for query in [{"limit": 101}, {"unknown": "value"}]:
        assert client.get("/api/v1/skills", params=query).status_code == 422
    assert client.get(f"/api/v1/skills/{uuid4()}").status_code == 404
    assert client.delete(f"/api/v1/admin/skills/{a}").status_code == 405


def test_chains_diamonds_cycles_replacement_and_rollback(
    storage_client: TestClient, seeded_storage: sessionmaker[Session]
) -> None:
    client = storage_client
    a, b, c, d = [create(client, code) for code in ["AA", "BB", "CC", "DD"]]
    for source, target in [(a, b), (a, c), (b, d), (c, d)]:
        assert add(client, source, target).status_code == 201
    before = graph(client)
    for source, target, code in [
        (a, a, "SELF_PREREQUISITE"),
        (a, b, "DUPLICATE_EDGE"),
        (b, a, "GRAPH_CYCLE"),
        (d, a, "GRAPH_CYCLE"),
        (str(uuid4()), a, "INVALID_SKILL"),
    ]:
        response = add(client, source, target)
        assert (
            response.status_code == 409 if code != "INVALID_SKILL" else response.status_code == 422
        )
        assert response.json()["error"]["code"] == code
        assert graph(client) == before
    replace_path = f"/api/v1/admin/skills/{b}/prerequisites"
    rejected = client.put(
        replace_path,
        json={"prerequisite_skill_ids": [d], "expected_graph_revision": before["graph_revision"]},
    )
    assert rejected.status_code == 409 and rejected.json()["error"]["code"] == "GRAPH_CYCLE"
    assert graph(client) == before
    assert (
        client.put(
            replace_path,
            json={
                "prerequisite_skill_ids": [a, a],
                "expected_graph_revision": before["graph_revision"],
            },
        ).status_code
        == 422
    )
    accepted = client.put(
        replace_path,
        json={"prerequisite_skill_ids": [c], "expected_graph_revision": before["graph_revision"]},
    )
    assert accepted.status_code == 200
    revision = accepted.json()["graph_revision"]
    no_change = client.put(
        replace_path, json={"prerequisite_skill_ids": [c], "expected_graph_revision": revision}
    )
    assert no_change.json()["graph_revision"] == revision
    removed = client.delete(f"{replace_path}/{c}", params={"expected_graph_revision": revision})
    assert removed.status_code == 204 and removed.content == b""
    assert (
        client.delete(
            f"{replace_path}/{c}",
            params={"expected_graph_revision": graph(client)["graph_revision"]},
        ).status_code
        == 404
    )
    with seeded_storage() as session:
        assert session.scalar(select(func.count()).select_from(models.SkillPrerequisite)) == 3


def test_neighborhood_direction_bounds_and_static_route(storage_client: TestClient) -> None:
    client = storage_client
    a, b, c, d = [create(client, code) for code in ["AA", "BB", "CC", "DD"]]
    for source, target in [(a, b), (b, c), (b, d)]:
        assert add(client, source, target).status_code == 201
    parents = graph(client, center_skill_id=b, direction="prerequisites")
    assert {node["id"] for node in parents["nodes"]} == {a, b}
    children = graph(client, center_skill_id=b, direction="dependents")
    assert {node["id"] for node in children["nodes"]} == {b, c, d}
    deep = graph(client, center_skill_id=c, direction="prerequisites", depth=2)
    assert {node["id"] for node in deep["nodes"]} == {a, b, c}
    for query in [{"max_nodes": 2}, {"max_edges": 1}, {"center_skill_id": b, "max_nodes": 1}]:
        response = client.get("/api/v1/skills/graph", params={"curriculum_id": CURRICULUM, **query})
        assert (
            response.status_code == 422 and response.json()["error"]["code"] == "GRAPH_READ_LIMIT"
        )
    for query in [{"depth": 6}, {"max_nodes": 101}, {"max_edges": 501}, {"unknown": 1}]:
        assert (
            client.get(
                "/api/v1/skills/graph", params={"curriculum_id": CURRICULUM, **query}
            ).status_code
            == 422
        )
    assert (
        client.get("/api/v1/skills/graph", params={"curriculum_id": str(uuid4())}).status_code
        == 404
    )


def test_archival_edges_and_mapping_validation(
    storage_client: TestClient, complete_draft: dict[str, object]
) -> None:
    client = storage_client
    a, b = create(client, "AA"), create(client, "BB")
    assert add(client, a, b).status_code == 201

    def archive(identifier: str, skill_revision: int = 1):
        return client.post(
            f"/api/v1/admin/skills/{identifier}/archive",
            headers={"Idempotency-Key": str(uuid4())},
            json={
                "expected_revision": skill_revision,
                "expected_graph_revision": graph(client)["graph_revision"],
            },
        )

    assert archive(a).json()["error"]["code"] == "SKILL_IN_USE"
    assert archive(b).json()["error"]["code"] == "SKILL_IN_USE"
    assert (
        client.delete(
            f"/api/v1/admin/skills/{b}/prerequisites/{a}",
            params={"expected_graph_revision": graph(client)["graph_revision"]},
        ).status_code
        == 204
    )
    response = archive(a)
    assert response.status_code == 200 and response.json()["archived_at"]
    assert client.get(f"/api/v1/skills/{a}").json() == response.json()
    assert a not in {item["id"] for item in client.get("/api/v1/skills").json()["items"]}
    assert a in {
        item["id"]
        for item in client.get("/api/v1/skills", params={"include_archived": True}).json()["items"]
    }
    assert a not in {item["id"] for item in graph(client)["nodes"]}
    assert add(client, a, b).status_code == 422
    assert add(client, b, a).json()["error"]["code"] == "SKILL_ARCHIVED"
    assert (
        client.patch(
            f"/api/v1/admin/skills/{a}", json={"expected_revision": 2, "title": "Again"}
        ).status_code
        == 409
    )
    assert archive(a, 2).json()["error"]["code"] == "SKILL_ARCHIVED"
    question = client.post(
        "/api/v1/admin/questions",
        headers={"Idempotency-Key": "mapped"},
        json={
            "code": "MAPPED",
            "family_id": "00000000-0000-0000-0000-000000000031",
            "draft": complete_draft,
        },
    )
    assert question.status_code == 201
    assert archive("00000000-0000-0000-0000-000000000011").json()["error"]["code"] == "SKILL_IN_USE"


def test_constraints_and_cross_curriculum_rejection(
    storage_client: TestClient, seeded_storage: sessionmaker[Session]
) -> None:
    client = storage_client
    a, b = create(client, "AA"), create(client, "BB")
    other_curriculum, other_skill = uuid4(), uuid4()
    with seeded_storage.begin() as session:
        session.add(models.Curriculum(id=other_curriculum, code="OTHER", title="Other"))
        session.flush()
        session.add(
            models.Skill(
                id=other_skill,
                curriculum_id=other_curriculum,
                code="OTHER",
                title="Other",
                competency="Different",
            )
        )
    assert add(client, str(other_skill), a).status_code == 422
    assert add(client, a, str(uuid4())).status_code == 404
    before = graph(client)
    for fields, state in [
        ({"prerequisite_skill_id": a, "dependent_skill_id": a}, "23514"),
        ({"prerequisite_skill_id": a, "dependent_skill_id": str(other_skill)}, "23503"),
        ({"prerequisite_skill_id": a, "dependent_skill_id": str(uuid4())}, "23503"),
    ]:
        with pytest.raises(IntegrityError) as caught, seeded_storage.begin() as session:
            session.add(
                models.SkillPrerequisite(
                    curriculum_id=UUID(CURRICULUM),
                    prerequisite_skill_id=UUID(fields["prerequisite_skill_id"]),
                    dependent_skill_id=UUID(fields["dependent_skill_id"]),
                )
            )
            session.flush()
        assert caught.value.orig.sqlstate == state
    assert add(client, a, b).status_code == 201
    with pytest.raises(IntegrityError) as caught, seeded_storage.begin() as session:
        session.add(
            models.SkillPrerequisite(
                curriculum_id=UUID(CURRICULUM),
                prerequisite_skill_id=UUID(a),
                dependent_skill_id=UUID(b),
            )
        )
        session.flush()
    assert caught.value.orig.sqlstate == "23505"
    count_before = len(graph(client)["nodes"])
    duplicate = client.post(
        "/api/v1/admin/skills",
        headers={"Idempotency-Key": "duplicate"},
        json={
            "curriculum_id": CURRICULUM,
            "code": "AA",
            "title": "Duplicate",
            "competency": "Duplicate",
        },
    )
    assert duplicate.status_code == 409
    assert len(graph(client)["nodes"]) == count_before
    assert graph(client)["graph_revision"] == before["graph_revision"] + 1
    missing = client.post(
        "/api/v1/admin/skills",
        headers={"Idempotency-Key": "missing"},
        json={
            "curriculum_id": str(uuid4()),
            "code": "MISSING",
            "title": "Missing",
            "competency": "Missing",
        },
    )
    assert missing.status_code == 404
    with seeded_storage() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(models.IdempotencyRecord)
                .where(models.IdempotencyRecord.key.in_(["duplicate", "missing"]))
            )
            == 0
        )


def test_graph_mutations_require_stored_admin(
    storage_client: TestClient, seeded_storage: sessionmaker[Session]
) -> None:
    client = storage_client
    a, b = create(client, "AA"), create(client, "BB")
    revision = graph(client)["graph_revision"]
    with seeded_storage.begin() as session:
        role = session.get(models.UserRole, (ADMIN, "content_admin"))
        session.delete(role)
    spoof = {"X-Role": "content_admin", "Idempotency-Key": "AA"}
    requests = [
        (
            "post",
            "/api/v1/admin/skills",
            {
                "curriculum_id": CURRICULUM,
                "code": "AA",
                "title": "AA",
                "competency": "Observable behavior",
            },
        ),
        ("patch", f"/api/v1/admin/skills/{a}", {"expected_revision": 1, "title": "Denied"}),
        (
            "post",
            f"/api/v1/admin/skills/{a}/archive",
            {"expected_revision": 1, "expected_graph_revision": revision},
        ),
        (
            "post",
            f"/api/v1/admin/skills/{b}/prerequisites",
            {"prerequisite_skill_id": a, "expected_graph_revision": revision},
        ),
        (
            "put",
            f"/api/v1/admin/skills/{b}/prerequisites",
            {"prerequisite_skill_ids": [a], "expected_graph_revision": revision},
        ),
    ]
    for method, path, body in requests:
        assert client.request(method, path, json=body, headers=spoof).status_code == 403
    assert (
        client.delete(
            f"/api/v1/admin/skills/{b}/prerequisites/{a}",
            params={"expected_graph_revision": revision},
            headers=spoof,
        ).status_code
        == 403
    )
    service = SkillService(seeded_storage)
    with pytest.raises(ContentError) as caught:
        service.change_prerequisites(
            Principal(ADMIN, frozenset({"content_admin"})),
            UUID(b),
            [UUID(a)],
            revision,
            "add",
            "stale-principal",
        )
    assert caught.value.code == "FORBIDDEN"
    assert graph(client)["graph_revision"] == revision
    client.app.state.settings = client.app.state.settings.model_copy(
        update={"development_user_id": None}
    )
    assert (
        client.post(
            f"/api/v1/admin/skills/{b}/prerequisites",
            json={"prerequisite_skill_id": a, "expected_graph_revision": revision},
            headers=spoof,
        ).status_code
        == 401
    )


def test_concurrent_opposing_edges_use_curriculum_lock_across_principals(
    storage_client: TestClient,
    seeded_storage: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    a, b = create(storage_client, "AA"), create(storage_client, "BB")
    second_admin = uuid4()
    seed_development_identity(
        seeded_storage, second_admin, "Second administrator", {"content_admin"}
    )
    revision = graph(storage_client)["graph_revision"]
    barrier = Barrier(2)
    original = SkillRepository.curriculum

    def synchronized(self, curriculum_id, *, write):
        if write:
            barrier.wait(timeout=5)
        return original(self, curriculum_id, write=write)

    monkeypatch.setattr(SkillRepository, "curriculum", synchronized)
    service = SkillService(seeded_storage)

    def mutate(user_id: UUID, prerequisite: str, dependent: str):
        try:
            return service.change_prerequisites(
                Principal(user_id, frozenset({"content_admin"})),
                UUID(dependent),
                [UUID(prerequisite)],
                revision,
                "add",
                str(uuid4()),
            )
        except ContentError as exception:
            return exception

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(mutate, ADMIN, a, b),
            executor.submit(mutate, second_admin, b, a),
        ]
        results = [future.result(timeout=10) for future in futures]
    monkeypatch.setattr(SkillRepository, "curriculum", original)
    failures = [result for result in results if isinstance(result, ContentError)]
    assert len(failures) == 1 and failures[0].code == "STALE_REVISION"
    current = graph(storage_client)
    assert len(current["edges"]) == 1 and current["graph_revision"] == revision + 1
    edge = current["edges"][0]
    retry = add(storage_client, edge["dependent_skill_id"], edge["prerequisite_skill_id"])
    assert retry.status_code == 409 and retry.json()["error"]["code"] == "GRAPH_CYCLE"
    assert graph(storage_client) == current


def test_replacement_flush_failure_rolls_back_graph_and_revision(
    storage_client: TestClient,
    seeded_storage: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    a, b, c = [create(storage_client, code) for code in ["AA", "BB", "CC"]]
    assert add(storage_client, a, b).status_code == 201
    before = graph(storage_client)
    original = SkillRepository.replace_incoming

    def fail_after_flush(self, dependent, prerequisites):
        original(self, dependent, prerequisites)
        self.session.flush()
        raise ContentError("INJECTED_FAILURE", "Replacement failed.")

    monkeypatch.setattr(SkillRepository, "replace_incoming", fail_after_flush)
    response = storage_client.put(
        f"/api/v1/admin/skills/{b}/prerequisites",
        json={"prerequisite_skill_ids": [c], "expected_graph_revision": before["graph_revision"]},
    )
    assert response.status_code == 409
    assert graph(storage_client) == before


def test_migration_preserves_existing_skills_and_question_mappings(
    database_connection: Connection,
) -> None:
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    config.attributes["connection"] = database_connection
    command.upgrade(config, "0002_question_storage")
    connection = database_connection
    connection.execute(
        text("INSERT INTO curricula(id,code,title) VALUES (:id,'EXISTING','Existing')"),
        {"id": UUID(CURRICULUM)},
    )
    connection.execute(
        text(
            "INSERT INTO skills(id,curriculum_id,code,title,competency) "
            "VALUES (:id,:curriculum,'EXISTING','Existing','Keep me')"
        ),
        {"id": UUID(int=11), "curriculum": UUID(CURRICULUM)},
    )
    connection.execute(
        text(
            "INSERT INTO question_families(id,code,novelty_definition) "
            "VALUES (:id,'EXISTING','Keep')"
        ),
        {"id": UUID(int=31)},
    )
    connection.execute(
        text(
            "INSERT INTO questions(id,code,family_id,revision,last_version_number) "
            "VALUES (:id,'EXISTING',:family,1,1)"
        ),
        {"id": UUID(int=41), "family": UUID(int=31)},
    )
    connection.execute(
        text(
            "INSERT INTO question_versions(id,question_id,version_number,revision,status,title,"
            "statement,track,difficulty,assessment_role,suggested_budget_seconds) "
            "VALUES (:id,:question,1,1,'draft','Keep','Keep','python','easy','practice',60)"
        ),
        {"id": UUID(int=51), "question": UUID(int=41)},
    )
    connection.execute(
        text(
            "INSERT INTO question_version_skills(version_id,skill_id,attribution_role,rubric_json) "
            "VALUES (:version,:skill,'primary','{}')"
        ),
        {"version": UUID(int=51), "skill": UUID(int=11)},
    )
    connection.commit()
    command.upgrade(config, "head")
    assert connection.scalar(text("SELECT competency FROM skills")) == "Keep me"
    assert connection.scalar(text("SELECT revision FROM skills")) == 1
    assert connection.scalar(text("SELECT graph_revision FROM curricula")) == 0
    assert connection.scalar(text("SELECT count(*) FROM question_version_skills")) == 1
    assert compare_metadata(MigrationContext.configure(connection), models.Base.metadata) == []
    connection.commit()
    command.downgrade(config, "0002_question_storage")
    assert connection.scalar(text("SELECT count(*) FROM question_version_skills")) == 1
    connection.commit()
    command.upgrade(config, "head")
    assert connection.scalar(text("SELECT competency FROM skills")) == "Keep me"
    connection.commit()


def test_concurrent_skill_edits_refresh_locked_revision(
    storage_client: TestClient,
    seeded_storage: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identifier = UUID(create(storage_client, "AA"))
    second_admin = uuid4()
    seed_development_identity(
        seeded_storage, second_admin, "Other administrator", {"content_admin"}
    )
    before = graph(storage_client)
    original = SkillRepository.curriculum
    barrier = Barrier(2)

    def synchronized(self, curriculum_id, *, write):
        if write:
            barrier.wait(timeout=5)
        return original(self, curriculum_id, write=write)

    monkeypatch.setattr(SkillRepository, "curriculum", synchronized)
    service = SkillService(seeded_storage)

    def edit(user_id: UUID, title: str):
        try:
            return service.patch(
                Principal(user_id, frozenset({"content_admin"})), identifier, 1, {"title": title}
            )
        except ContentError as exception:
            return exception

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(edit, ADMIN, "First"),
            executor.submit(edit, second_admin, "Second"),
        ]
        results = [future.result(timeout=10) for future in futures]
    monkeypatch.setattr(SkillRepository, "curriculum", original)
    failures = [result for result in results if isinstance(result, ContentError)]
    assert len(failures) == 1 and failures[0].code == "STALE_REVISION"
    record = storage_client.get(f"/api/v1/skills/{identifier}").json()
    assert record["revision"] == 2
    assert graph(storage_client)["graph_revision"] == before["graph_revision"] + 1


def test_question_mapping_lock_prevents_archival_race(
    storage_client: TestClient,
    seeded_storage: sessionmaker[Session],
    complete_draft: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from threading import Event

    from mastery_backend.domain.content import DraftContent
    from mastery_backend.infrastructure.database.content_repository import ContentRepository

    skill_id = UUID(create(storage_client, "AA"))
    content = DraftContent.model_validate(
        {
            **complete_draft,
            "skill_mappings": [
                {
                    "skill_id": str(skill_id),
                    "attribution_role": "primary",
                    "rubric": {"check": "Valid"},
                }
            ],
        }
    )
    question = storage_client.post(
        "/api/v1/admin/questions",
        headers={"Idempotency-Key": "unmapped"},
        json={
            "code": "UNMAPPED",
            "family_id": "00000000-0000-0000-0000-000000000031",
            "draft": {"title": "Unmapped", "statement": "Unmapped"},
        },
    )
    assert question.status_code == 201
    revision = graph(storage_client)["graph_revision"]
    attempted_lock = Event()
    original = SkillRepository.skill

    def observed(self, identifier, *, lock=False):
        if lock:
            attempted_lock.set()
        return original(self, identifier, lock=lock)

    monkeypatch.setattr(SkillRepository, "skill", observed)
    service = SkillService(seeded_storage)

    def archive():
        try:
            return service.archive(
                Principal(ADMIN, frozenset({"content_admin"})), "race", skill_id, 1, revision
            )
        except ContentError as exception:
            return exception

    with ThreadPoolExecutor(max_workers=1) as executor:
        with seeded_storage.begin() as session:
            ContentRepository(session).validate_references(content)
            future = executor.submit(archive)
            assert attempted_lock.wait(timeout=5)
            assert not future.done()
            session.add(
                models.QuestionVersionSkill(
                    version_id=UUID(question.json()["id"]),
                    skill_id=skill_id,
                    attribution_role="primary",
                    rubric_json={"check": "Valid"},
                )
            )
            session.flush()
        result = future.result(timeout=10)
    assert isinstance(result, ContentError) and result.code == "SKILL_IN_USE"
    assert storage_client.get(f"/api/v1/skills/{skill_id}").json()["archived_at"] is None
    assert graph(storage_client)["graph_revision"] == revision


def test_create_validation_and_prerequisite_command_replay(storage_client: TestClient) -> None:
    client = storage_client
    body = {
        "curriculum_id": CURRICULUM,
        "code": "VALID",
        "title": "Valid",
        "competency": "Behavior",
    }
    for invalid in [
        {"code": "lowercase"},
        {"title": " "},
        {"competency": "\n"},
        {"curriculum_id": "invalid"},
        {"unknown": 1},
    ]:
        response = client.post(
            "/api/v1/admin/skills", headers={"Idempotency-Key": "invalid"}, json={**body, **invalid}
        )
        assert response.status_code == 422
    assert client.post("/api/v1/admin/skills", json=body).status_code == 422
    a, b = create(client, "AA"), create(client, "BB")
    path = f"/api/v1/admin/skills/{b}/prerequisites"
    body = {"prerequisite_skill_id": a, "expected_graph_revision": graph(client)["graph_revision"]}
    headers = {"Idempotency-Key": "add-once"}
    assert client.post(path, json=body).status_code == 422
    first = client.post(path, json=body, headers=headers)
    assert first.status_code == 201
    replay = client.post(path, json=body, headers=headers)
    assert replay.status_code == 201 and replay.json() == first.json()
    assert replay.headers["Idempotency-Replayed"] == "true"
    conflict = client.post(path, json={**body, "prerequisite_skill_id": b}, headers=headers)
    assert (
        conflict.status_code == 409 and conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    )
    assert graph(client)["graph_revision"] == first.json()["graph_revision"]


def test_prerequisites_leave_published_content_available_and_archival_preserves_mapping(
    storage_client: TestClient,
    seeded_storage: sessionmaker[Session],
    complete_draft: dict[str, object],
) -> None:
    from mastery_backend.api.dependencies import reference_verifier
    from mastery_backend.application.publication_verification import VerificationProof

    class TransitionOnlyVerifier:
        def recheck(self, session, snapshot, proof):
            """Test-only transition fixture."""

        def verify(self, snapshot: PublicationSnapshot) -> VerificationProof:
            immutable_snapshot, content_hash = snapshot.immutable_snapshot, snapshot.content_hash
            assert isinstance(immutable_snapshot, bytes)
            return VerificationProof(
                content_hash=content_hash,
                verifier_version="test-only",
                verification_id="graph-guidance-test",
            )

    client = storage_client
    skill_id = "00000000-0000-0000-0000-000000000011"
    prerequisite = create(client, "PREREQUISITE")
    assert add(client, prerequisite, skill_id).status_code == 201
    draft_response = client.post(
        "/api/v1/admin/questions",
        headers={"Idempotency-Key": "guidance"},
        json={
            "code": "GUIDANCE",
            "family_id": "00000000-0000-0000-0000-000000000031",
            "draft": complete_draft,
        },
    )
    assert draft_response.status_code == 201
    draft = draft_response.json()
    client.app.dependency_overrides[reference_verifier] = TransitionOnlyVerifier
    assert (
        client.post(
            f"/api/v1/admin/question-versions/{draft['id']}/publish",
            headers={"Idempotency-Key": "publish-guidance"},
            json={"expected_revision": 1},
        ).status_code
        == 200
    )
    responses = [
        client.get(f"/api/v1/questions/{draft['question_id']}"),
        client.get("/api/v1/skills/graph", params={"curriculum_id": CURRICULUM}),
        client.get("/api/v1/skills"),
        client.get(f"/api/v1/skills/{skill_id}"),
    ]
    for response in responses:
        assert response.status_code == 200
        for marker in [
            "PRIVATE_TEST_INPUT",
            "PRIVATE_TEST_OUTPUT",
            "PRIVATE_HINT",
            "PRIVATE_SOLUTION",
            "PRIVATE_RUBRIC",
        ]:
            assert marker not in response.text
    assert (
        client.delete(
            f"/api/v1/admin/skills/{skill_id}/prerequisites/{prerequisite}",
            params={"expected_graph_revision": graph(client)["graph_revision"]},
        ).status_code
        == 204
    )
    archive_body = {
        "expected_revision": 1,
        "expected_graph_revision": graph(client)["graph_revision"],
    }
    denied = client.post(
        f"/api/v1/admin/skills/{skill_id}/archive",
        headers={"Idempotency-Key": "archive-skill"},
        json=archive_body,
    )
    assert denied.status_code == 409 and denied.json()["error"]["code"] == "SKILL_IN_USE"
    assert (
        client.post(
            f"/api/v1/admin/questions/{draft['question_id']}/archive",
            headers={"Idempotency-Key": "archive-question"},
            json={"expected_revision": 1},
        ).status_code
        == 200
    )
    archived = client.post(
        f"/api/v1/admin/skills/{skill_id}/archive",
        headers={"Idempotency-Key": "archive-skill"},
        json=archive_body,
    )
    assert archived.status_code == 200 and archived.json()["archived_at"]
    with seeded_storage() as session:
        mapping = session.get(models.QuestionVersionSkill, (UUID(draft["id"]), UUID(skill_id)))
        assert mapping is not None and mapping.rubric_json == {"criterion": "PRIVATE_RUBRIC"}
    assert (
        client.get(f"/api/v1/admin/question-versions/{draft['id']}").json()["status"] == "published"
    )
