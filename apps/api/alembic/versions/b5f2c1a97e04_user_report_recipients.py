"""users.report_to / users.report_cc

Report recipients were the server-wide `REPORT_TO` / `REPORT_CC` env vars.
Moving them per-user so each account picks its own destinations without a
redeploy; the sender stays in the environment.

Existing rows default to empty, which means "no reports" — there is no env
fallback. Anyone relying on the old vars must set them in the UI once.

Revision ID: b5f2c1a97e04
Revises: 821323652708
Create Date: 2026-08-24 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b5f2c1a97e04"
down_revision: str | Sequence[str] | None = "821323652708"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("report_to", sa.String(length=2000), server_default="", nullable=False),
    )
    op.add_column(
        "users",
        sa.Column("report_cc", sa.String(length=2000), server_default="", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("users", "report_cc")
    op.drop_column("users", "report_to")
