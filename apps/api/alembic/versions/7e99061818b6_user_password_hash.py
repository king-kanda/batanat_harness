"""user password hash

Revision ID: 7e99061818b6
Revises: af648b75cbe1
Create Date: auto

Note: autogenerate originally emitted drops for LangGraph's checkpoint_* tables
here, because they exist in the database but not in our metadata. They are
managed by LangGraph's own setup() and must not be touched — env.py now filters
them out of autogenerate so this cannot recur.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "7e99061818b6"
down_revision: str | Sequence[str] | None = "af648b75cbe1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("password_hash", sa.String(length=255), nullable=True))
    op.add_column("users", sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "last_login_at")
    op.drop_column("users", "password_hash")
