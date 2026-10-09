"""Normalized local identity and question storage; freeze published content."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002_question_storage"
down_revision = "0001_database_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "curricula",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.create_table(
        "patterns",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.create_table(
        "question_families",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("novelty_definition", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("normalized_email", sa.String(length=320), nullable=True),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("status IN ('active', 'disabled')", name="ck_user_status"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("normalized_email"),
    )
    op.create_table(
        "idempotency_records",
        sa.Column("principal_id", sa.Uuid(), nullable=False),
        sa.Column("operation", sa.String(length=200), nullable=False),
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("response_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("location", sa.String(length=200), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["principal_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("principal_id", "operation", "key"),
    )
    op.create_table(
        "questions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("last_version_number", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("revision > 0", name="ck_question_revision"),
        sa.ForeignKeyConstraint(["family_id"], ["question_families.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.create_table(
        "skills",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("curriculum_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("competency", sa.Text(), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["curriculum_id"], ["curricula.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("curriculum_id", "code", name="uq_skill_curriculum_code"),
        sa.UniqueConstraint("id", "curriculum_id", name="uq_skill_id_curriculum"),
    )
    op.create_table(
        "user_roles",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.CheckConstraint("role IN ('learner', 'content_admin')", name="ck_user_role"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("user_id", "role"),
    )
    op.create_table(
        "question_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("question_id", sa.Uuid(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("track", sa.String(length=64), nullable=False),
        sa.Column("difficulty", sa.String(length=16), nullable=False),
        sa.Column("assessment_role", sa.String(length=32), nullable=False),
        sa.Column("suggested_budget_seconds", sa.Integer(), nullable=False),
        sa.Column("contract_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("verification_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(status = 'draft' AND published_at IS NULL AND verification_json IS NULL) OR "
            "(status = 'published' AND published_at IS NOT NULL AND verification_json IS NOT NULL)",
            name="ck_version_publication",
        ),
        sa.CheckConstraint(
            "assessment_role IN ('practice','assessment','transfer','delayed_review')",
            name="ck_version_assessment_role",
        ),
        sa.CheckConstraint("difficulty IN ('easy','medium','hard')", name="ck_version_difficulty"),
        sa.CheckConstraint("suggested_budget_seconds > 0", name="ck_version_budget"),
        sa.CheckConstraint("version_number > 0 AND revision > 0", name="ck_version_counters"),
        sa.ForeignKeyConstraint(["question_id"], ["questions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("question_id", "version_number", name="uq_question_version_number"),
    )
    op.create_index(
        "ix_question_published_version",
        "question_versions",
        ["question_id", "version_number"],
        unique=False,
        postgresql_where=sa.text("status = 'published'"),
    )
    op.create_table(
        "question_assistance_steps",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("next_budget_seconds", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "kind IN ('directional','pattern','pseudocode','partial_code','full_solution')",
            name="ck_assistance_kind",
        ),
        sa.CheckConstraint("position > 0 AND next_budget_seconds > 0", name="ck_assistance_bounds"),
        sa.ForeignKeyConstraint(["version_id"], ["question_versions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("version_id", "position", name="uq_assistance_position"),
    )
    op.create_table(
        "question_examples",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("input_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("output_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.CheckConstraint("position > 0", name="ck_example_position"),
        sa.ForeignKeyConstraint(["version_id"], ["question_versions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("version_id", "position", name="uq_example_position"),
    )
    op.create_table(
        "question_links",
        sa.Column("source_version_id", sa.Uuid(), nullable=False),
        sa.Column("target_version_id", sa.Uuid(), nullable=False),
        sa.Column("link_type", sa.String(length=32), nullable=False),
        sa.CheckConstraint("link_type IN ('variation','transfer','review')", name="ck_link_type"),
        sa.CheckConstraint("source_version_id <> target_version_id", name="ck_link_distinct"),
        sa.ForeignKeyConstraint(
            ["source_version_id"], ["question_versions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["target_version_id"], ["question_versions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("source_version_id", "target_version_id", "link_type"),
    )
    op.create_table(
        "question_solutions",
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("reference_code", sa.Text(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("expected_complexity", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["version_id"], ["question_versions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("version_id"),
    )
    op.create_table(
        "question_test_cases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("visibility", sa.String(length=16), nullable=False),
        sa.Column("input_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("expected_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("assertion_rule", sa.String(length=32), nullable=False),
        sa.Column("critical", sa.Boolean(), nullable=False),
        sa.CheckConstraint("assertion_rule = 'equals'", name="ck_test_assertion"),
        sa.CheckConstraint("visibility IN ('public','private')", name="ck_test_visibility"),
        sa.CheckConstraint("position > 0", name="ck_test_position"),
        sa.ForeignKeyConstraint(["version_id"], ["question_versions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("version_id", "position", name="uq_test_position"),
    )
    op.create_table(
        "question_version_modes",
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("mode", sa.String(length=32), nullable=False),
        sa.CheckConstraint(
            "mode IN ('practice','assessment','transfer','delayed_review')", name="ck_mode"
        ),
        sa.ForeignKeyConstraint(["version_id"], ["question_versions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("version_id", "mode"),
    )
    op.create_table(
        "question_version_patterns",
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("pattern_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["pattern_id"], ["patterns.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["version_id"], ["question_versions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("version_id", "pattern_id"),
    )
    op.create_table(
        "question_version_skills",
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("skill_id", sa.Uuid(), nullable=False),
        sa.Column("attribution_role", sa.String(length=16), nullable=False),
        sa.Column("rubric_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.CheckConstraint(
            "attribution_role IN ('primary','secondary')", name="ck_attribution_role"
        ),
        sa.ForeignKeyConstraint(["skill_id"], ["skills.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["version_id"], ["question_versions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("version_id", "skill_id"),
    )
    op.create_index(
        "uq_version_primary_skill",
        "question_version_skills",
        ["version_id"],
        unique=True,
        postgresql_where=sa.text("attribution_role = 'primary'"),
    )

    install_content_guards()


def downgrade() -> None:
    remove_content_guards()
    op.drop_index(
        "uq_version_primary_skill",
        table_name="question_version_skills",
        postgresql_where=sa.text("attribution_role = 'primary'"),
    )
    op.drop_table("question_version_skills")
    op.drop_table("question_version_patterns")
    op.drop_table("question_version_modes")
    op.drop_table("question_test_cases")
    op.drop_table("question_solutions")
    op.drop_table("question_links")
    op.drop_table("question_examples")
    op.drop_table("question_assistance_steps")
    op.drop_index(
        "ix_question_published_version",
        table_name="question_versions",
        postgresql_where=sa.text("status = 'published'"),
    )
    op.drop_table("question_versions")
    op.drop_table("user_roles")
    op.drop_table("skills")
    op.drop_table("questions")
    op.drop_table("idempotency_records")
    op.drop_table("users")
    op.drop_table("question_families")
    op.drop_table("patterns")
    op.drop_table("curricula")


CHILD_TABLES = {
    "question_version_modes": "version_id",
    "question_version_skills": "version_id",
    "question_version_patterns": "version_id",
    "question_examples": "version_id",
    "question_test_cases": "version_id",
    "question_assistance_steps": "version_id",
    "question_solutions": "version_id",
    "question_links": "source_version_id",
}


def install_content_guards() -> None:
    op.execute("""
        CREATE FUNCTION guard_question_version() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                IF NEW.status <> 'draft' THEN
                    RAISE EXCEPTION 'Versions must start as drafts' USING ERRCODE = '23514';
                END IF;
                RETURN NEW;
            END IF;
            IF OLD.status = 'published' THEN
                RAISE EXCEPTION 'Published versions are immutable' USING ERRCODE = '23514';
            END IF;
            IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
            IF NEW.question_id <> OLD.question_id OR NEW.version_number <> OLD.version_number THEN
                RAISE EXCEPTION 'Version identity is immutable' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$
    """)
    op.execute("""
        CREATE TRIGGER freeze_question_version
        BEFORE INSERT OR UPDATE OR DELETE ON question_versions
        FOR EACH ROW EXECUTE FUNCTION guard_question_version()
    """)
    op.execute("""
        CREATE FUNCTION guard_question_child() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            owner_id uuid;
            version_status text;
        BEGIN
            IF TG_OP = 'DELETE' THEN
                owner_id := (to_jsonb(OLD) ->> TG_ARGV[0])::uuid;
            ELSE
                owner_id := (to_jsonb(NEW) ->> TG_ARGV[0])::uuid;
                IF TG_OP = 'UPDATE' AND owner_id IS DISTINCT FROM
                    (to_jsonb(OLD) ->> TG_ARGV[0])::uuid THEN
                    RAISE EXCEPTION 'Content cannot move between versions' USING ERRCODE = '23514';
                END IF;
            END IF;
            -- Serialize with publication, including insertions into empty collections.
            SELECT status INTO version_status FROM question_versions
                WHERE id = owner_id FOR UPDATE;
            IF version_status = 'published' THEN
                RAISE EXCEPTION 'Published version assets are immutable' USING ERRCODE = '23514';
            END IF;
            IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
            RETURN NEW;
        END $$
    """)
    for table_name, owner_column in CHILD_TABLES.items():
        op.execute(f"""
            CREATE TRIGGER freeze_question_content
            BEFORE INSERT OR UPDATE OR DELETE ON {table_name}
            FOR EACH ROW EXECUTE FUNCTION guard_question_child('{owner_column}')
        """)
    op.execute("""
        CREATE FUNCTION guard_question_identity() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.code <> OLD.code OR NEW.family_id <> OLD.family_id THEN
                RAISE EXCEPTION 'Question identity is immutable' USING ERRCODE = '23514';
            END IF;
            IF OLD.archived_at IS NOT NULL AND NEW.archived_at IS DISTINCT FROM OLD.archived_at THEN
                RAISE EXCEPTION 'Question archival is permanent' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$
    """)
    op.execute("""
        CREATE TRIGGER freeze_question_identity BEFORE UPDATE ON questions
        FOR EACH ROW EXECUTE FUNCTION guard_question_identity()
    """)


def remove_content_guards() -> None:
    for table_name in CHILD_TABLES:
        op.execute(f"DROP TRIGGER freeze_question_content ON {table_name}")
    op.execute("DROP TRIGGER freeze_question_version ON question_versions")
    op.execute("DROP TRIGGER freeze_question_identity ON questions")
    op.execute("DROP FUNCTION guard_question_child()")
    op.execute("DROP FUNCTION guard_question_version()")
    op.execute("DROP FUNCTION guard_question_identity()")
