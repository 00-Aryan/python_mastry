"""Local authoring setup transactions, independent of HTTP and CLI parsing."""

from typing import Literal
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from mastery_backend.domain.content import ContentError
from mastery_backend.domain.content_seed import ReferenceCatalogSeed, SkillSeed
from mastery_backend.domain.identity import require_content_admin
from mastery_backend.infrastructure.database import content_models as models
from mastery_backend.infrastructure.database.identity_repository import load_principal


def seed_development_identity(
    factory: sessionmaker[Session],
    user_id: UUID,
    display_name: str,
    roles: set[Literal["learner", "content_admin"]],
) -> None:
    if not display_name.strip() or len(display_name) > 200 or not roles:
        raise ContentError("INVALID_IDENTITY", "A display name and explicit roles are required.")
    with factory.begin() as session:
        existing = session.get(models.User, user_id, with_for_update=True)
        if existing is None:
            session.add(models.User(id=user_id, display_name=display_name))
            session.flush()
        elif existing.display_name != display_name or existing.status != "active":
            raise ContentError("IDENTITY_CONFLICT", "Existing identity differs from the seed.")
        for role in roles:
            if session.get(models.UserRole, (user_id, role)) is None:
                session.add(models.UserRole(user_id=user_id, role=role))
        session.flush()


def seed_reference_catalog(
    factory: sessionmaker[Session],
    user_id: UUID | None,
    catalog: ReferenceCatalogSeed,
) -> None:
    try:
        with factory.begin() as session:
            require_content_admin(load_principal(session, user_id, lock=True))
            groups = (
                (models.Curriculum, catalog.curricula),
                (models.Skill, catalog.skills),
                (models.Pattern, catalog.patterns),
                (models.QuestionFamily, catalog.question_families),
            )
            for model, values in groups:
                # Shared curriculum locks also cover bootstrap insertions. Sorting avoids
                # opposing lock order when two administrators seed several curricula.
                curricula = {}
                if model is models.Skill:
                    for curriculum_id in sorted({value.curriculum_id for value in catalog.skills}):
                        curricula[curriculum_id] = session.get(
                            models.Curriculum, curriculum_id, with_for_update=True
                        )
                for value in values:
                    curriculum = None
                    if isinstance(value, SkillSeed):
                        curriculum = curricula[value.curriculum_id]
                    existing = session.get(model, value.id)
                    attributes = value.model_dump()
                    if existing is None:
                        session.add(model(**attributes))
                        if curriculum is not None:
                            curriculum.graph_revision += 1
                    elif any(
                        getattr(existing, name) != content for name, content in attributes.items()
                    ):
                        raise ContentError(
                            "REFERENCE_CONFLICT", "Existing reference differs from its seed."
                        )
                session.flush()
    except IntegrityError:
        raise ContentError(
            "REFERENCE_CONFLICT", "Reference seed violates a database constraint."
        ) from None
