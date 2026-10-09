"""Normalized content/identity facts; constraints also apply to direct SQL writes."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("status IN ('active', 'disabled')", name="ck_user_status"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    normalized_email: Mapped[str | None] = mapped_column(String(320), unique=True)
    display_name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(16), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserRole(Base):
    __tablename__ = "user_roles"
    __table_args__ = (CheckConstraint("role IN ('learner', 'content_admin')", name="ck_user_role"),)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(32), primary_key=True)


class Curriculum(Base):
    __tablename__ = "curricula"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    code: Mapped[str] = mapped_column(String(64), unique=True)
    title: Mapped[str] = mapped_column(String(200))


class Skill(Base):
    __tablename__ = "skills"
    __table_args__ = (
        UniqueConstraint("curriculum_id", "code", name="uq_skill_curriculum_code"),
        UniqueConstraint("id", "curriculum_id", name="uq_skill_id_curriculum"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    curriculum_id: Mapped[UUID] = mapped_column(ForeignKey("curricula.id", ondelete="RESTRICT"))
    code: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(200))
    competency: Mapped[str] = mapped_column(Text)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Pattern(Base):
    __tablename__ = "patterns"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    code: Mapped[str] = mapped_column(String(64), unique=True)
    title: Mapped[str] = mapped_column(String(200))


class QuestionFamily(Base):
    __tablename__ = "question_families"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    code: Mapped[str] = mapped_column(String(64), unique=True)
    novelty_definition: Mapped[str] = mapped_column(Text)


class Question(Base):
    __tablename__ = "questions"
    __table_args__ = (CheckConstraint("revision > 0", name="ck_question_revision"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    code: Mapped[str] = mapped_column(String(64), unique=True)
    family_id: Mapped[UUID] = mapped_column(ForeignKey("question_families.id", ondelete="RESTRICT"))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    last_version_number: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class QuestionVersion(Base):
    __tablename__ = "question_versions"
    __table_args__ = (
        UniqueConstraint("question_id", "version_number", name="uq_question_version_number"),
        CheckConstraint("version_number > 0 AND revision > 0", name="ck_version_counters"),
        CheckConstraint("difficulty IN ('easy','medium','hard')", name="ck_version_difficulty"),
        CheckConstraint(
            "assessment_role IN ('practice','assessment','transfer','delayed_review')",
            name="ck_version_assessment_role",
        ),
        CheckConstraint("suggested_budget_seconds > 0", name="ck_version_budget"),
        CheckConstraint(
            "(status = 'draft' AND published_at IS NULL AND verification_json IS NULL) OR "
            "(status = 'published' AND published_at IS NOT NULL AND verification_json IS NOT NULL)",
            name="ck_version_publication",
        ),
        Index(
            "ix_question_published_version",
            "question_id",
            "version_number",
            postgresql_where=text("status = 'published'"),
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    question_id: Mapped[UUID] = mapped_column(ForeignKey("questions.id", ondelete="RESTRICT"))
    version_number: Mapped[int] = mapped_column(Integer)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(16), default="draft")
    title: Mapped[str] = mapped_column(String(200))
    statement: Mapped[str] = mapped_column(Text)
    track: Mapped[str] = mapped_column(String(64))
    difficulty: Mapped[str] = mapped_column(String(16))
    assessment_role: Mapped[str] = mapped_column(String(32))
    suggested_budget_seconds: Mapped[int] = mapped_column(Integer)
    contract_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    verification_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    modes: Mapped[list[QuestionVersionMode]] = relationship(
        cascade="all, delete-orphan", lazy="selectin"
    )
    skills: Mapped[list[QuestionVersionSkill]] = relationship(
        cascade="all, delete-orphan", lazy="selectin"
    )
    patterns: Mapped[list[QuestionVersionPattern]] = relationship(
        cascade="all, delete-orphan", lazy="selectin"
    )
    examples: Mapped[list[QuestionExample]] = relationship(
        cascade="all, delete-orphan", lazy="selectin"
    )
    test_cases: Mapped[list[QuestionTestCase]] = relationship(
        cascade="all, delete-orphan", lazy="selectin"
    )
    assistance_steps: Mapped[list[QuestionAssistanceStep]] = relationship(
        cascade="all, delete-orphan", lazy="selectin"
    )
    solution: Mapped[QuestionSolution | None] = relationship(
        cascade="all, delete-orphan", lazy="selectin"
    )
    links: Mapped[list[QuestionLink]] = relationship(
        foreign_keys="QuestionLink.source_version_id", cascade="all, delete-orphan", lazy="selectin"
    )


class QuestionVersionMode(Base):
    __tablename__ = "question_version_modes"
    __table_args__ = (
        CheckConstraint(
            "mode IN ('practice','assessment','transfer','delayed_review')", name="ck_mode"
        ),
    )
    version_id: Mapped[UUID] = mapped_column(
        ForeignKey("question_versions.id", ondelete="RESTRICT"), primary_key=True
    )
    mode: Mapped[str] = mapped_column(String(32), primary_key=True)


class QuestionVersionSkill(Base):
    __tablename__ = "question_version_skills"
    __table_args__ = (
        CheckConstraint("attribution_role IN ('primary','secondary')", name="ck_attribution_role"),
        Index(
            "uq_version_primary_skill",
            "version_id",
            unique=True,
            postgresql_where=text("attribution_role = 'primary'"),
        ),
    )
    version_id: Mapped[UUID] = mapped_column(
        ForeignKey("question_versions.id", ondelete="RESTRICT"), primary_key=True
    )
    skill_id: Mapped[UUID] = mapped_column(
        ForeignKey("skills.id", ondelete="RESTRICT"), primary_key=True
    )
    attribution_role: Mapped[str] = mapped_column(String(16))
    rubric_json: Mapped[dict[str, Any]] = mapped_column(JSONB)


class QuestionVersionPattern(Base):
    __tablename__ = "question_version_patterns"
    version_id: Mapped[UUID] = mapped_column(
        ForeignKey("question_versions.id", ondelete="RESTRICT"), primary_key=True
    )
    pattern_id: Mapped[UUID] = mapped_column(
        ForeignKey("patterns.id", ondelete="RESTRICT"), primary_key=True
    )


class QuestionExample(Base):
    __tablename__ = "question_examples"
    __table_args__ = (
        UniqueConstraint("version_id", "position", name="uq_example_position"),
        CheckConstraint("position > 0", name="ck_example_position"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    version_id: Mapped[UUID] = mapped_column(
        ForeignKey("question_versions.id", ondelete="RESTRICT")
    )
    position: Mapped[int] = mapped_column(Integer)
    input_json: Mapped[list[Any]] = mapped_column(JSONB)
    output_json: Mapped[Any] = mapped_column(JSONB)
    explanation: Mapped[str] = mapped_column(Text)


class QuestionTestCase(Base):
    __tablename__ = "question_test_cases"
    __table_args__ = (
        UniqueConstraint("version_id", "position", name="uq_test_position"),
        CheckConstraint("position > 0", name="ck_test_position"),
        CheckConstraint("visibility IN ('public','private')", name="ck_test_visibility"),
        CheckConstraint("assertion_rule = 'equals'", name="ck_test_assertion"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    version_id: Mapped[UUID] = mapped_column(
        ForeignKey("question_versions.id", ondelete="RESTRICT")
    )
    position: Mapped[int] = mapped_column(Integer)
    visibility: Mapped[str] = mapped_column(String(16))
    input_json: Mapped[list[Any]] = mapped_column(JSONB)
    expected_json: Mapped[Any] = mapped_column(JSONB)
    assertion_rule: Mapped[str] = mapped_column(String(32))
    critical: Mapped[bool]


class QuestionAssistanceStep(Base):
    __tablename__ = "question_assistance_steps"
    __table_args__ = (
        UniqueConstraint("version_id", "position", name="uq_assistance_position"),
        CheckConstraint("position > 0 AND next_budget_seconds > 0", name="ck_assistance_bounds"),
        CheckConstraint(
            "kind IN ('directional','pattern','pseudocode','partial_code','full_solution')",
            name="ck_assistance_kind",
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    version_id: Mapped[UUID] = mapped_column(
        ForeignKey("question_versions.id", ondelete="RESTRICT")
    )
    position: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(32))
    content: Mapped[str] = mapped_column(Text)
    next_budget_seconds: Mapped[int] = mapped_column(Integer)


class QuestionSolution(Base):
    __tablename__ = "question_solutions"
    version_id: Mapped[UUID] = mapped_column(
        ForeignKey("question_versions.id", ondelete="RESTRICT"), primary_key=True
    )
    reference_code: Mapped[str] = mapped_column(Text)
    explanation: Mapped[str] = mapped_column(Text)
    expected_complexity: Mapped[str] = mapped_column(Text)


class QuestionLink(Base):
    __tablename__ = "question_links"
    __table_args__ = (
        CheckConstraint("source_version_id <> target_version_id", name="ck_link_distinct"),
        CheckConstraint("link_type IN ('variation','transfer','review')", name="ck_link_type"),
    )
    source_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("question_versions.id", ondelete="RESTRICT"), primary_key=True
    )
    target_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("question_versions.id", ondelete="RESTRICT"), primary_key=True
    )
    link_type: Mapped[str] = mapped_column(String(32), primary_key=True)


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    principal_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), primary_key=True
    )
    operation: Mapped[str] = mapped_column(String(200), primary_key=True)
    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    response_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status_code: Mapped[int] = mapped_column(Integer)
    location: Mapped[str | None] = mapped_column(String(200))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
