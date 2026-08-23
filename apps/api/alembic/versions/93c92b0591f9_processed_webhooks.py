"""processed_webhooks

One row per webhook delivery already handled, so a provider's retry is not
treated as a new event. The unique constraint on (provider, external_id) is the
mechanism — handling is guarded by an insert, so two concurrent deliveries of
the same message cannot both win.

Revision ID: 93c92b0591f9
Revises: 5e624a06542b
Create Date: 2026-08-23 23:24:22.513149
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "93c92b0591f9"
down_revision: str | Sequence[str] | None = "5e624a06542b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "processed_webhooks",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("external_id", sa.String(length=200), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_processed_webhooks")),
        sa.UniqueConstraint(
            "provider", "external_id", name=op.f("uq_processed_webhooks_provider_external_id")
        ),
    )
    # Only the recent past matters; the nightly prune walks this index.
    op.create_index(
        "ix_processed_webhooks_created_at", "processed_webhooks", ["created_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_processed_webhooks_created_at", table_name="processed_webhooks")
    op.drop_table("processed_webhooks")
