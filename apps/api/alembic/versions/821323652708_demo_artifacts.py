"""demo_artifacts

A ledger of rows created by the demo seeder, so the "clear demo data" button in
the app deletes exactly those and nothing else. Clearing by pattern — ids that
start with `demo-`, URLs on a fixture domain — is a delete that will eventually
match something real.


Revision ID: 821323652708
Revises: 93c92b0591f9
Create Date: 2026-08-23 23:48:14.819634

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "821323652708"
down_revision: str | Sequence[str] | None = "93c92b0591f9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "demo_artifacts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("entity_type", sa.String(length=40), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_demo_artifacts_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_demo_artifacts")),
        sa.UniqueConstraint(
            "entity_type", "entity_id", name=op.f("uq_demo_artifacts_entity_type_entity_id")
        ),
    )
    op.create_index("ix_demo_artifacts_user", "demo_artifacts", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_demo_artifacts_user", table_name="demo_artifacts")
    op.drop_table("demo_artifacts")
