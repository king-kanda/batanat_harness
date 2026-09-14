"""merge password reset branch with the main schema branch

Revision ID: 7f8e9a0b1c2d
Revises: 6d7e8f9a0b1c, baec147286cf
"""

from collections.abc import Sequence

revision: str = "7f8e9a0b1c2d"
down_revision: str | Sequence[str] | None = ("6d7e8f9a0b1c", "baec147286cf")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
