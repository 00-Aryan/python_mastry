"""Establish migration history before introducing content/identity tables.

Alembic owns alembic_version and its primary key. No application entities exist
in this connection-only increment, so there is no application DDL to invent.
"""

revision = "0001_database_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
