import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Event
from typing import Any
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from fastapi.testclient import TestClient
from httpx2 import Response
from sqlalchemy import Connection, event, func, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from mastery_backend.api.dependencies import reference_verifier
from mastery_backend.application.content_service import ContentService
from mastery_backend.application.publication_verification import (
    UnavailableReferenceVerifier,
    VerificationProof,
)
from mastery_backend.domain.content import ContentError, DraftContent
from mastery_backend.domain.identity import Principal
from mastery_backend.infrastructure.database import content_models as models

ADMIN_ID = UUID("00000000-0000-0000-0000-000000000001")
FAMILY_ID = UUID("00000000-0000-0000-0000-000000000031")
ADMIN = Principal(ADMIN_ID, frozenset({"learner", "content_admin"}))
PRIVATE_MARKERS = (
    "PRIVATE_TEST_INPUT",
    "PRIVATE_TEST_OUTPUT",
    "PRIVATE_HINT",
    "PRIVATE_SOLUTION",
    "PRIVATE_RUBRIC",
)


class TestReferenceVerifier:
    """Test-only proof of transition plumbing, never proof of executable correctness."""

    __test__ = False

    def verify(self, immutable_snapshot: bytes, content_hash: str) -> VerificationProof:
        assert isinstance(immutable_snapshot, bytes)
        assert json.loads(immutable_snapshot)["solution"]["reference_code"]
        return VerificationProof(
            content_hash=content_hash, verifier_version="test-only", verification_id="fixture"
        )


def create_draft(
    client: TestClient, content: dict[str, object], code: str = "ECHO-01", key: str = "create-01"
) -> dict[str, Any]:
    response = client.post(
        "/api/v1/admin/questions",
        json={"code": code, "family_id": str(FAMILY_ID), "draft": content},
        headers={"Idempotency-Key": key},
    )
    assert response.status_code == 201, response.text
    assert response.headers["location"].endswith(response.json()["id"])
    return response.json()


def publish(client: TestClient, draft: dict[str, Any], key: str = "publish-01") -> dict[str, Any]:
    client.app.dependency_overrides[reference_verifier] = TestReferenceVerifier
    response = client.post(
        f"/api/v1/admin/question-versions/{draft['id']}/publish",
        json={"expected_revision": draft["revision"]},
        headers={"Idempotency-Key": key},
    )
    assert response.status_code == 200, response.text
    return response.json()


def assert_no_private_content(response: Response) -> None:
    for marker in PRIVATE_MARKERS:
        assert marker not in response.text
    assert "reference_code" not in response.text
    assert "test_cases" not in response.text
    assert "assistance_steps" not in response.text


def test_crud_revision_replay_and_delete(
    storage_client: TestClient,
    complete_draft: dict[str, object],
    seeded_storage: sessionmaker[Session],
) -> None:
    draft = create_draft(storage_client, complete_draft)
    identifier = draft["id"]
    replay = storage_client.post(
        "/api/v1/admin/questions",
        json={"code": "ECHO-01", "family_id": str(FAMILY_ID), "draft": complete_draft},
        headers={"Idempotency-Key": "create-01"},
    )
    assert replay.json() == draft
    assert replay.headers["idempotency-replayed"] == "true"
    assert storage_client.get(f"/api/v1/admin/question-versions/{identifier}").json() == draft
    assert storage_client.get(f"/api/v1/question-versions/{identifier}").status_code == 404
    assert storage_client.get("/api/v1/questions").json() == {"items": [], "next_cursor": None}
    edited = storage_client.patch(
        f"/api/v1/admin/question-versions/{identifier}",
        json={"expected_revision": 1, "title": "Edited", "pattern_ids": [], "test_cases": []},
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["revision"] == 2
    assert edited.json()["test_cases"] == []
    assert edited.json()["statement"] == draft["statement"]
    stale = storage_client.patch(
        f"/api/v1/admin/question-versions/{identifier}",
        json={"expected_revision": 1, "title": "Overwrite"},
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "STALE_REVISION"
    assert (
        storage_client.delete(
            f"/api/v1/admin/question-versions/{identifier}?expected_revision=1"
        ).status_code
        == 409
    )
    assert (
        storage_client.delete(
            f"/api/v1/admin/question-versions/{identifier}?expected_revision=2"
        ).status_code
        == 204
    )
    assert storage_client.get(f"/api/v1/admin/question-versions/{identifier}").status_code == 404
    created = storage_client.post(
        f"/api/v1/admin/questions/{draft['question_id']}/versions",
        json=complete_draft,
        headers={"Idempotency-Key": "next-version"},
    )
    assert created.status_code == 201, created.text
    assert created.json()["version_number"] == 2  # Deleted version numbers are never reused.
    with seeded_storage.begin() as session:
        assert session.scalar(select(func.count()).select_from(models.QuestionVersion)) == 1


def test_conflicts_invalid_inputs_and_rollback(
    storage_client: TestClient,
    complete_draft: dict[str, object],
    seeded_storage: sessionmaker[Session],
) -> None:
    draft = create_draft(storage_client, complete_draft)
    same_key = storage_client.post(
        "/api/v1/admin/questions",
        json={"code": "DIFFERENT", "family_id": str(FAMILY_ID), "draft": complete_draft},
        headers={"Idempotency-Key": "create-01"},
    )
    assert same_key.status_code == 409
    assert same_key.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    duplicate = storage_client.post(
        "/api/v1/admin/questions",
        json={"code": "ECHO-01", "family_id": str(FAMILY_ID), "draft": complete_draft},
        headers={"Idempotency-Key": "duplicate"},
    )
    assert duplicate.status_code == 409
    for changes in (
        {"solution": {"reference_code": "PRIVATE_SOLUTION", "unexpected": "PRIVATE_TEST_INPUT"}},
        {"user_id": str(ADMIN_ID)},
        {"title": None},
        {"expected_revision": 0},
    ):
        response = storage_client.patch(
            f"/api/v1/admin/question-versions/{draft['id']}",
            json={"expected_revision": 1, **changes},
        )
        assert response.status_code == 422
        for marker in PRIVATE_MARKERS:
            assert marker not in response.text
    invalid_ref = storage_client.patch(
        f"/api/v1/admin/question-versions/{draft['id']}",
        json={"expected_revision": 1, "title": "Must roll back", "pattern_ids": [str(uuid4())]},
    )
    assert invalid_ref.status_code == 422
    after = storage_client.get(f"/api/v1/admin/question-versions/{draft['id']}").json()
    assert after["title"] == draft["title"] and after["revision"] == 1
    with seeded_storage.begin() as session:
        assert session.scalar(select(func.count()).select_from(models.Question)) == 1
        assert session.scalar(select(func.count()).select_from(models.IdempotencyRecord)) == 1
    assert storage_client.get("/api/v1/questions/not-a-uuid").status_code == 422
    assert storage_client.get("/api/v1/questions?limit=0").status_code == 422
    assert storage_client.get("/api/v1/questions?owner_id=private").status_code == 422


def test_publication_unavailable_changes_nothing(
    storage_client: TestClient,
    complete_draft: dict[str, object],
    seeded_storage: sessionmaker[Session],
) -> None:
    draft = create_draft(storage_client, complete_draft)
    response = storage_client.post(
        f"/api/v1/admin/question-versions/{draft['id']}/publish",
        json={"expected_revision": 1},
        headers={"Idempotency-Key": "unavailable", "X-Request-ID": "verify-unavailable"},
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "VERIFICATION_UNAVAILABLE"
    assert response.json()["error"]["request_id"] == "verify-unavailable"
    assert_no_private_content(response)
    assert storage_client.get(f"/api/v1/admin/question-versions/{draft['id']}").json() == draft
    with seeded_storage.begin() as session:
        record = session.get(models.QuestionVersion, UUID(draft["id"]))
        assert record.status == "draft" and record.verification_json is None
        assert record.published_at is None and record.revision == 1
        assert session.scalar(select(func.count()).select_from(models.IdempotencyRecord)) == 1
    assert storage_client.get(f"/api/v1/question-versions/{draft['id']}").status_code == 404


def test_publish_public_projection_versions_archive(
    storage_client: TestClient, complete_draft: dict[str, object]
) -> None:
    draft = create_draft(storage_client, complete_draft)
    published = publish(storage_client, draft)
    assert published["status"] == "published" and published["revision"] == 2
    replay = storage_client.post(
        f"/api/v1/admin/question-versions/{draft['id']}/publish",
        json={"expected_revision": 1},
        headers={"Idempotency-Key": "publish-01"},
    )
    assert replay.status_code == 200 and replay.json() == published
    assert replay.headers["idempotency-replayed"] == "true"
    for path in (
        f"/api/v1/questions/{draft['question_id']}",
        f"/api/v1/question-versions/{draft['id']}",
        "/api/v1/questions",
    ):
        response = storage_client.get(path)
        assert response.status_code == 200
        assert_no_private_content(response)
    immutable = storage_client.patch(
        f"/api/v1/admin/question-versions/{draft['id']}",
        json={"expected_revision": 2, "statement": "Alter"},
    )
    assert (
        immutable.status_code == 409 and immutable.json()["error"]["code"] == "PUBLISHED_IMMUTABLE"
    )
    assert (
        storage_client.delete(
            f"/api/v1/admin/question-versions/{draft['id']}?expected_revision=2"
        ).status_code
        == 409
    )
    second = storage_client.post(
        f"/api/v1/admin/questions/{draft['question_id']}/versions",
        json={**complete_draft, "title": "Second version"},
        headers={"Idempotency-Key": "new-version"},
    )
    assert second.status_code == 201
    assert (
        storage_client.get(f"/api/v1/questions/{draft['question_id']}").json()["version_number"]
        == 1
    )
    publish(storage_client, second.json(), "publish-second")
    assert (
        storage_client.get(f"/api/v1/questions/{draft['question_id']}").json()["version_number"]
        == 2
    )
    assert (
        storage_client.get(f"/api/v1/question-versions/{draft['id']}").json()["version_number"] == 1
    )
    archived = storage_client.post(
        f"/api/v1/admin/questions/{draft['question_id']}/archive",
        json={"expected_revision": 1},
        headers={"Idempotency-Key": "archive"},
    )
    assert archived.status_code == 200
    for identifier in (draft["id"], second.json()["id"]):
        assert storage_client.get(f"/api/v1/question-versions/{identifier}").status_code == 404
    assert storage_client.get("/api/v1/questions").json()["items"] == []
    assert storage_client.get(f"/api/v1/admin/question-versions/{draft['id']}").status_code == 200
    assert (
        storage_client.post(
            f"/api/v1/admin/questions/{draft['question_id']}/versions",
            json=complete_draft,
            headers={"Idempotency-Key": "after-archive"},
        ).status_code
        == 409
    )


def test_concurrent_edits_one_success_one_conflict(
    storage_client: TestClient, complete_draft: dict[str, object]
) -> None:
    draft = create_draft(storage_client, complete_draft)
    barrier = Barrier(2)

    def edit(title: str) -> Response:
        barrier.wait(timeout=5)
        return storage_client.patch(
            f"/api/v1/admin/question-versions/{draft['id']}",
            json={"expected_revision": 1, "title": title},
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(edit, ["Editor A", "Editor B"]))
    assert sorted(result.status_code for result in results) == [200, 409]
    conflict = next(result for result in results if result.status_code == 409)
    assert conflict.json()["error"]["code"] == "STALE_REVISION"
    assert (
        storage_client.get(f"/api/v1/admin/question-versions/{draft['id']}").json()["revision"] == 2
    )


@pytest.mark.parametrize("mutation", ["revision", "hash", "archive"])
def test_publication_verifies_outside_transaction_and_rechecks_snapshot(
    seeded_storage: sessionmaker[Session], complete_draft: dict[str, object], mutation: str
) -> None:
    service = ContentService(seeded_storage, TestReferenceVerifier())
    draft = service.create_question(
        ADMIN, "create", "ECHO-01", FAMILY_ID, DraftContent.model_validate(complete_draft)
    )
    version_id = UUID(draft.body["id"])
    entered = Event()
    release = Event()

    class BlockingVerifier(TestReferenceVerifier):
        def verify(self, immutable_snapshot: bytes, content_hash: str) -> VerificationProof:
            assert seeded_storage.kw["bind"].pool.checkedout() == 0
            entered.set()
            assert release.wait(timeout=10)
            return super().verify(immutable_snapshot, content_hash)

    publishing_service = ContentService(seeded_storage, BlockingVerifier())
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(publishing_service.publish_version, ADMIN, "publish", version_id, 1)
        try:
            assert entered.wait(timeout=5)
            if mutation == "revision":
                service.patch_draft(ADMIN, version_id, 1, {"title": "Concurrent edit"})
            elif mutation == "hash":
                # Privileged SQL simulates an edit that bypasses application revision accounting.
                with seeded_storage.begin() as session:
                    session.execute(
                        text(
                            "UPDATE question_test_cases SET expected_json = '\"changed\"'::jsonb "
                            "WHERE version_id=:id"
                        ),
                        {"id": version_id},
                    )
            else:
                service.archive_question(ADMIN, "archive", UUID(draft.body["question_id"]), 1)
        finally:
            release.set()
        with pytest.raises(ContentError) as caught:
            future.result(timeout=10)
    assert caught.value.code == ("QUESTION_ARCHIVED" if mutation == "archive" else "STALE_REVISION")
    with seeded_storage.begin() as session:
        assert session.get(models.QuestionVersion, version_id).status == "draft"
        assert (
            session.get(
                models.IdempotencyRecord,
                (ADMIN_ID, f"POST /api/v1/admin/question-versions/{version_id}/publish", "publish"),
            )
            is None
        )


def test_published_sql_parent_and_all_assets_are_immutable(
    storage_client: TestClient,
    complete_draft: dict[str, object],
    seeded_storage: sessionmaker[Session],
) -> None:
    first = publish(storage_client, create_draft(storage_client, complete_draft))
    # Include a link in a second published version to exercise the link guard.
    second = create_draft(
        storage_client,
        {
            **complete_draft,
            "revision_links": [{"target_version_id": first["id"], "link_type": "variation"}],
        },
        "ECHO-02",
        "create-02",
    )
    published = publish(storage_client, second, "publish-02")
    version_id = UUID(published["id"])
    statements = [
        "UPDATE question_versions SET title='tampered' WHERE id=:id",
        "UPDATE question_versions SET status='draft', published_at=NULL, "
        "verification_json=NULL WHERE id=:id",
        "DELETE FROM question_versions WHERE id=:id",
        "UPDATE question_test_cases SET expected_json='null'::jsonb WHERE version_id=:id",
        "UPDATE question_assistance_steps SET content='tampered' WHERE version_id=:id",
        "UPDATE question_solutions SET reference_code='tampered' WHERE version_id=:id",
        "UPDATE question_version_skills SET rubric_json='{}'::jsonb WHERE version_id=:id",
        "UPDATE question_version_patterns SET pattern_id=pattern_id WHERE version_id=:id",
        "UPDATE question_version_modes SET mode=mode WHERE version_id=:id",
        "UPDATE question_examples SET explanation='tampered' WHERE version_id=:id",
        "UPDATE question_links SET link_type=link_type WHERE source_version_id=:id",
        "INSERT INTO question_version_modes VALUES (:id, 'transfer')",
    ]
    for table in (
        "question_test_cases",
        "question_assistance_steps",
        "question_solutions",
        "question_version_skills",
        "question_version_patterns",
        "question_version_modes",
        "question_examples",
        "question_links",
    ):
        column = "source_version_id" if table == "question_links" else "version_id"
        statements.append(f"DELETE FROM {table} WHERE {column}=:id")
        statements.append(f"INSERT INTO {table} SELECT * FROM {table} WHERE {column}=:id")
    for statement in statements:
        with pytest.raises(IntegrityError) as caught, seeded_storage.begin() as session:
            session.execute(text(statement), {"id": version_id})
        assert caught.value.orig.sqlstate == "23514", statement
    assert storage_client.get(f"/api/v1/admin/question-versions/{version_id}").json() == published


def test_migration_upgrade_from_baseline_constraints_and_replay(
    database_connection: Connection,
) -> None:
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    config.attributes["connection"] = database_connection
    command.upgrade(config, "0001_database_baseline")
    assert inspect(database_connection).get_table_names() == ["alembic_version"]
    database_connection.commit()
    command.upgrade(config, "head")
    database_connection.commit()
    inspector = inspect(database_connection)
    assert set(models.Base.metadata.tables).issubset(inspector.get_table_names())
    assert (
        compare_metadata(MigrationContext.configure(database_connection), models.Base.metadata)
        == []
    )
    database_connection.commit()
    command.upgrade(config, "head")
    assert (
        database_connection.scalar(text("SELECT version_num FROM alembic_version"))
        == "0005_progressive_assistance"
    )
    database_connection.commit()
    command.downgrade(config, "0001_database_baseline")
    assert inspect(database_connection).get_table_names() == ["alembic_version"]
    database_connection.commit()
    command.upgrade(config, "head")
    database_connection.commit()


def test_authorization_uses_database_and_denies_missing_or_disabled_identity(
    storage_client: TestClient,
    complete_draft: dict[str, object],
    seeded_storage: sessionmaker[Session],
) -> None:
    draft = create_draft(storage_client, complete_draft)
    path = f"/api/v1/admin/question-versions/{draft['id']}"
    with seeded_storage.begin() as session:
        session.execute(
            text("DELETE FROM user_roles WHERE user_id=:id AND role='content_admin'"),
            {"id": ADMIN_ID},
        )
    denied = storage_client.patch(
        path,
        json={"expected_revision": 1, "title": "Unauthorized"},
        headers={"X-Role": "content_admin", "X-User-ID": str(ADMIN_ID)},
    )
    assert denied.status_code == 403
    assert storage_client.get(path).status_code == 403
    assert_no_private_content(denied)
    # A previously successful command must not replay after the role was revoked.
    replay = storage_client.post(
        "/api/v1/admin/questions",
        json={"code": "ECHO-01", "family_id": str(FAMILY_ID), "draft": complete_draft},
        headers={"Idempotency-Key": "create-01"},
    )
    assert replay.status_code == 403
    service = ContentService(seeded_storage, TestReferenceVerifier())
    with pytest.raises(ContentError, match="administrator"):
        service.patch_draft(ADMIN, UUID(draft["id"]), 1, {"title": "Stale principal"})
    with seeded_storage.begin() as session:
        session.add(models.UserRole(user_id=ADMIN_ID, role="content_admin"))
        session.execute(text("UPDATE users SET status='disabled' WHERE id=:id"), {"id": ADMIN_ID})
    assert storage_client.get(path).status_code == 401
    settings = storage_client.app.state.settings
    storage_client.app.state.settings = settings.model_copy(update={"development_user_id": None})
    assert (
        storage_client.patch(
            path, json={"expected_revision": 1, "title": "Missing identity"}
        ).status_code
        == 401
    )
    storage_client.app.state.settings = settings.model_copy(update={"development_user_id": uuid4()})
    assert storage_client.get(path).status_code == 401


def test_local_origin_guard_and_missing_idempotency_key(
    storage_client: TestClient,
    complete_draft: dict[str, object],
) -> None:
    body = {"code": "ECHO-01", "family_id": str(FAMILY_ID), "draft": complete_draft}
    assert storage_client.post("/api/v1/admin/questions", json=body).status_code == 422
    for headers in ({"Origin": "https://attacker.invalid"}, {"Sec-Fetch-Site": "cross-site"}):
        response = storage_client.post(
            "/api/v1/admin/questions", json=body, headers={"Idempotency-Key": "blocked", **headers}
        )
        assert response.status_code == 403
        assert_no_private_content(response)
    assert storage_client.get("/api/v1/questions").json()["items"] == []


def test_catalog_pages_filters_cursors_and_query_boundaries(
    storage_client: TestClient,
    complete_draft: dict[str, object],
    seeded_storage: sessionmaker[Session],
) -> None:
    for number in range(3):
        draft = create_draft(
            storage_client, complete_draft, f"ECHO-{number:02}", f"create-{number}"
        )
        publish(storage_client, draft, f"publish-{number}")
    statements = []

    def record_query(
        conn: object,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        statements.append(statement)

    engine = seeded_storage.kw["bind"]
    event.listen(engine, "before_cursor_execute", record_query)
    try:
        page = storage_client.get("/api/v1/questions?limit=2&difficulty=easy")
    finally:
        event.remove(engine, "before_cursor_execute", record_query)
    assert page.status_code == 200
    assert len(page.json()["items"]) == 2
    assert len(statements) == 6  # One catalog query and five batched public projections.
    assert not any(
        table in statement
        for statement in statements
        for table in ("question_test_cases", "question_assistance_steps", "question_solutions")
    )
    cursor = page.json()["next_cursor"]
    next_page = storage_client.get(
        "/api/v1/questions", params={"limit": 2, "difficulty": "easy", "cursor": cursor}
    )
    assert next_page.status_code == 200 and len(next_page.json()["items"]) == 1
    ids = [item["id"] for item in page.json()["items"] + next_page.json()["items"]]
    assert len(set(ids)) == 3
    assert next_page.json()["next_cursor"] is None
    assert_no_private_content(page)
    assert_no_private_content(next_page)
    assert (
        storage_client.get(
            "/api/v1/questions", params={"cursor": cursor, "difficulty": "hard"}
        ).status_code
        == 400
    )
    assert storage_client.get("/api/v1/questions?cursor=not-base64").status_code == 400
    assert (
        len(
            storage_client.get(
                "/api/v1/questions?skill_id=00000000-0000-0000-0000-000000000011"
            ).json()["items"]
        )
        == 3
    )
    assert (
        len(
            storage_client.get(
                "/api/v1/questions?curriculum_id=00000000-0000-0000-0000-000000000010"
            ).json()["items"]
        )
        == 3
    )
    assert storage_client.get("/api/v1/questions?difficulty=hard").json()["items"] == []
    settings = storage_client.app.state.settings
    storage_client.app.state.settings = settings.model_copy(update={"max_page_size": 1})
    assert storage_client.get("/api/v1/questions?limit=2").status_code == 422


def test_database_constraints_on_drafts(
    seeded_storage: sessionmaker[Session], complete_draft: dict[str, object]
) -> None:
    service = ContentService(seeded_storage, UnavailableReferenceVerifier())
    draft = service.create_question(
        ADMIN, "create", "ECHO-01", FAMILY_ID, DraftContent.model_validate(complete_draft)
    )
    identifier = UUID(draft.body["id"])
    question_id = UUID(draft.body["question_id"])
    # Seed another valid skill for a direct-SQL primary-attribution conflict.
    with seeded_storage.begin() as session:
        session.add(
            models.Skill(
                id=UUID("00000000-0000-0000-0000-000000000012"),
                curriculum_id=UUID("00000000-0000-0000-0000-000000000010"),
                code="SECOND",
                title="Second",
                competency="Second",
            )
        )
    cases = [
        (
            "INSERT INTO question_version_skills VALUES "
            "(:id, '00000000-0000-0000-0000-000000000012', 'primary', '{}')",
            "23505",
        ),
        (
            "INSERT INTO question_version_patterns VALUES "
            "(:id, '00000000-0000-0000-0000-000000000099')",
            "23503",
        ),
        ("UPDATE question_versions SET suggested_budget_seconds=0 WHERE id=:id", "23514"),
        ("UPDATE question_test_cases SET position=0 WHERE version_id=:id", "23514"),
        ("UPDATE question_test_cases SET visibility='unknown' WHERE version_id=:id", "23514"),
        ("INSERT INTO question_version_modes VALUES (:id, 'unknown')", "23514"),
        ("UPDATE question_versions SET status='published' WHERE id=:id", "23514"),
        (
            "INSERT INTO question_examples SELECT * FROM question_examples WHERE version_id=:id",
            "23505",
        ),
        ("UPDATE questions SET code='CHANGED' WHERE id=:question_id", "23514"),
    ]
    for statement, sqlstate in cases:
        with pytest.raises(IntegrityError) as caught, seeded_storage.begin() as session:
            session.execute(text(statement), {"id": identifier, "question_id": question_id})
        assert caught.value.orig.sqlstate == sqlstate
    with pytest.raises(IntegrityError), seeded_storage.begin() as session:
        existing = session.get(models.QuestionVersion, identifier)
        duplicate = models.QuestionVersion(
            id=uuid4(),
            question_id=question_id,
            version_number=1,
            title=existing.title,
            statement=existing.statement,
            track=existing.track,
            difficulty=existing.difficulty,
            assessment_role=existing.assessment_role,
            suggested_budget_seconds=existing.suggested_budget_seconds,
        )
        session.add(duplicate)
    assert service.read_admin_version(ADMIN, identifier).revision == 1


def test_reference_seed_is_idempotent_and_failed_seed_rolls_back(
    seeded_storage: sessionmaker[Session],
) -> None:
    from mastery_backend.application.content_seed_service import seed_reference_catalog
    from mastery_backend.domain.content_seed import ReferenceCatalogSeed

    catalog = ReferenceCatalogSeed.model_validate(
        {
            "patterns": [
                {"id": "00000000-0000-0000-0000-000000000022", "code": "LOOP", "title": "Loop"}
            ]
        }
    )
    seed_reference_catalog(seeded_storage, ADMIN_ID, catalog)
    seed_reference_catalog(seeded_storage, ADMIN_ID, catalog)
    invalid = ReferenceCatalogSeed.model_validate(
        {
            "curricula": [
                {"id": "00000000-0000-0000-0000-000000000090", "code": "NEW", "title": "New"}
            ],
            "skills": [
                {
                    "id": "00000000-0000-0000-0000-000000000091",
                    "curriculum_id": str(uuid4()),
                    "code": "BAD",
                    "title": "Bad",
                    "competency": "Missing FK",
                }
            ],
        }
    )
    with pytest.raises(ContentError):
        seed_reference_catalog(seeded_storage, ADMIN_ID, invalid)
    with seeded_storage.begin() as session:
        assert session.get(models.Curriculum, UUID("00000000-0000-0000-0000-000000000090")) is None
        assert session.scalar(select(func.count()).select_from(models.Pattern)) == 2


def test_verification_hash_mismatch_cannot_publish(
    seeded_storage: sessionmaker[Session],
    complete_draft: dict[str, object],
) -> None:
    class WrongProof(TestReferenceVerifier):
        def verify(self, immutable_snapshot: bytes, content_hash: str) -> VerificationProof:
            return VerificationProof(
                content_hash="0" * 64, verifier_version="test-only", verification_id="wrong"
            )

    service = ContentService(seeded_storage, WrongProof())
    draft = service.create_question(
        ADMIN, "create", "ECHO-01", FAMILY_ID, DraftContent.model_validate(complete_draft)
    )
    with pytest.raises(ContentError) as caught:
        service.publish_version(ADMIN, "publish", UUID(draft.body["id"]), 1)
    assert caught.value.code == "VERIFICATION_MISMATCH"
    assert service.read_admin_version(ADMIN, UUID(draft.body["id"])).status == "draft"


def test_content_cli_setup_and_safe_errors(
    seeded_storage: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from mastery_backend import content_cli

    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/mastery_test")
    monkeypatch.setenv("DEVELOPMENT_USER_ID", str(ADMIN_ID))
    engine = seeded_storage.kw["bind"]
    monkeypatch.setattr(content_cli, "create_database_engine", lambda settings: engine)
    monkeypatch.setattr(
        content_cli, "create_session_factory", lambda database_engine: seeded_storage
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "mastery-content",
            "seed-identity",
            "--user-id",
            str(ADMIN_ID),
            "--display-name",
            "Test administrator",
            "--role",
            "content_admin",
        ],
    )
    content_cli.main()
    assert "Seeded local identity" in capsys.readouterr().out
    filename = tmp_path / "references.json"
    filename.write_text(
        json.dumps(
            {
                "patterns": [
                    {"id": "00000000-0000-0000-0000-000000000022", "code": "LOOP", "title": "Loop"}
                ]
            }
        )
    )
    monkeypatch.setattr("sys.argv", ["mastery-content", "seed-references", str(filename)])
    content_cli.main()
    assert "Authoring references seeded" in capsys.readouterr().out
    filename.write_text('{"patterns": [{"private": "PRIVATE_TEST_INPUT"}]}')
    with pytest.raises(SystemExit) as caught:
        content_cli.main()
    assert "PRIVATE_TEST_INPUT" not in str(caught.value)
    monkeypatch.setenv("DATABASE_URL", "PRIVATE_INVALID_DATABASE")
    with pytest.raises(SystemExit) as caught:
        content_cli.main()
    assert "database_url" in str(caught.value)
    assert "PRIVATE_INVALID_DATABASE" not in str(caught.value)


def test_content_errors_do_not_disclose_private_data_or_stack_traces(
    storage_client: TestClient,
    complete_draft: dict[str, object],
) -> None:
    draft = create_draft(storage_client, complete_draft)

    class FailedVerifier(TestReferenceVerifier):
        def verify(self, immutable_snapshot: bytes, content_hash: str) -> VerificationProof:
            raise RuntimeError("PRIVATE_SOLUTION PRIVATE_TEST_INPUT")

    storage_client.app.dependency_overrides[reference_verifier] = FailedVerifier
    response = storage_client.post(
        f"/api/v1/admin/question-versions/{draft['id']}/publish",
        json={"expected_revision": 1},
        headers={"Idempotency-Key": "unexpected"},
    )
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert_no_private_content(response)
    assert "Traceback" not in response.text
    assert (
        storage_client.get(f"/api/v1/admin/question-versions/{draft['id']}").json()["status"]
        == "draft"
    )


def test_draft_replacement_failure_rolls_back_all_children(
    storage_client: TestClient,
    complete_draft: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mastery_backend.infrastructure.database.content_repository import ContentRepository

    draft = create_draft(storage_client, complete_draft)
    original = ContentRepository.replace_content

    def fail_after_flush(
        repository: ContentRepository, version: models.QuestionVersion, content: DraftContent
    ) -> None:
        original(repository, version, content)
        repository.session.flush()
        raise RuntimeError("PRIVATE_SOLUTION replacement failed")

    with monkeypatch.context() as changes:
        changes.setattr(ContentRepository, "replace_content", fail_after_flush)
        response = storage_client.patch(
            f"/api/v1/admin/question-versions/{draft['id']}",
            json={
                "expected_revision": 1,
                "title": "Must roll back",
                "test_cases": [],
                "solution": None,
            },
        )
    assert response.status_code == 500
    assert_no_private_content(response)
    assert storage_client.get(f"/api/v1/admin/question-versions/{draft['id']}").json() == draft


def test_concurrent_identical_post_replays_one_committed_result(
    storage_client: TestClient,
    complete_draft: dict[str, object],
    seeded_storage: sessionmaker[Session],
) -> None:
    barrier = Barrier(2)

    def create(_: int) -> Response:
        barrier.wait(timeout=5)
        return storage_client.post(
            "/api/v1/admin/questions",
            json={"code": "ECHO-01", "family_id": str(FAMILY_ID), "draft": complete_draft},
            headers={"Idempotency-Key": "concurrent-create"},
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(create, [1, 2]))
    assert [response.status_code for response in responses] == [201, 201]
    assert responses[0].json() == responses[1].json()
    assert (
        sum(response.headers.get("idempotency-replayed") == "true" for response in responses) == 1
    )
    with seeded_storage.begin() as session:
        assert session.scalar(select(func.count()).select_from(models.Question)) == 1
        assert session.scalar(select(func.count()).select_from(models.IdempotencyRecord)) == 1
