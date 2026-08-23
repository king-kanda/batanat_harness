"""users.must_change_password

Records whether an account is still on the seeded development password, rather
than working it out by hashing the default on every request. See
`auth/router.py` — that check sat on `/api/auth/me`, which the UI calls on every
page load, and scrypt is deliberately expensive.

Existing rows default to false: an account already in the database has been
through a login, and claiming otherwise would put a warning banner in front of
someone who does not need it. The seeder sets the flag for accounts it creates.

Revision ID: 5e624a06542b
Revises: caeb4249dcf4
Create Date: 2026-08-23 23:01:34.239135
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "5e624a06542b"
down_revision: str | Sequence[str] | None = "caeb4249dcf4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "must_change_password",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "must_change_password")
