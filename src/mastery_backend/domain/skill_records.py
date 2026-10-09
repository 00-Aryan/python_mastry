"""Bounded skill/graph input values and explicit public records."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import ConfigDict, Field

from mastery_backend.domain.content import Code, ContentValue

SkillTitle = Annotated[str, Field(min_length=1, max_length=200, pattern=r"\S")]
Competency = Annotated[str, Field(min_length=1, max_length=65536, pattern=r"\S")]


class SkillContent(ContentValue):
    title: SkillTitle
    competency: Competency


class CreateSkill(SkillContent):
    curriculum_id: UUID
    code: Code


class SkillRecord(CreateSkill):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)
    id: UUID
    revision: int
    archived_at: datetime | None


class EdgeRecord(ContentValue):
    prerequisite_skill_id: UUID
    dependent_skill_id: UUID


class GraphRecord(ContentValue):
    curriculum_id: UUID
    graph_revision: int
    nodes: list[SkillRecord]
    edges: list[EdgeRecord]


class SkillListQuery(ContentValue):
    curriculum_id: UUID | None = None
    include_archived: bool = False
    limit: int = Field(default=20, ge=1, le=100)
    cursor: str | None = Field(default=None, max_length=2048)


class SkillPage(ContentValue):
    items: list[SkillRecord]
    next_cursor: str | None


class GraphQuery(ContentValue):
    curriculum_id: UUID
    center_skill_id: UUID | None = None
    direction: Literal["prerequisites", "dependents", "both"] = "both"
    depth: int = Field(default=1, ge=1, le=5)
    max_nodes: int = Field(default=100, ge=1, le=100)
    max_edges: int = Field(default=200, ge=1, le=500)
