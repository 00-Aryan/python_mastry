"""A server-derived local principal, never supplied through request fields."""

from dataclasses import dataclass
from uuid import UUID

from mastery_backend.domain.content import ContentError


@dataclass(frozen=True)
class Principal:
    user_id: UUID
    roles: frozenset[str]


def require_content_admin(principal: Principal) -> None:
    if "content_admin" not in principal.roles:
        raise ContentError("FORBIDDEN", "Content administrator role required.")


def require_learner(principal: Principal) -> None:
    if "learner" not in principal.roles:
        raise ContentError("FORBIDDEN", "Learner role required.")
