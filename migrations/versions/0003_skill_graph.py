"""Skill revisions and normalized same-curriculum prerequisite edges."""

import sqlalchemy as sa
from alembic import op

revision = "0003_skill_graph"
down_revision = "0002_question_storage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "curricula", sa.Column("graph_revision", sa.Integer(), server_default="0", nullable=False)
    )
    op.create_check_constraint("ck_curriculum_graph_revision", "curricula", "graph_revision >= 0")
    op.add_column("skills", sa.Column("revision", sa.Integer(), server_default="1", nullable=False))
    op.create_check_constraint("ck_skill_revision", "skills", "revision > 0")
    op.create_table(
        "skill_prerequisites",
        sa.Column("prerequisite_skill_id", sa.Uuid(), nullable=False),
        sa.Column("dependent_skill_id", sa.Uuid(), nullable=False),
        sa.Column("curriculum_id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("prerequisite_skill_id", "dependent_skill_id"),
        sa.CheckConstraint(
            "prerequisite_skill_id <> dependent_skill_id", name="ck_prerequisite_distinct"
        ),
        sa.ForeignKeyConstraint(
            ["prerequisite_skill_id", "curriculum_id"],
            ["skills.id", "skills.curriculum_id"],
            ondelete="RESTRICT",
            name="fk_prerequisite_curriculum",
        ),
        sa.ForeignKeyConstraint(
            ["dependent_skill_id", "curriculum_id"],
            ["skills.id", "skills.curriculum_id"],
            ondelete="RESTRICT",
            name="fk_dependent_curriculum",
        ),
    )
    op.create_index(
        "ix_prerequisite_outgoing",
        "skill_prerequisites",
        ["curriculum_id", "prerequisite_skill_id"],
    )
    op.create_index(
        "ix_prerequisite_incoming", "skill_prerequisites", ["curriculum_id", "dependent_skill_id"]
    )


def downgrade() -> None:
    op.drop_table("skill_prerequisites")
    op.drop_constraint("ck_skill_revision", "skills")
    op.drop_column("skills", "revision")
    op.drop_constraint("ck_curriculum_graph_revision", "curricula")
    op.drop_column("curricula", "graph_revision")
