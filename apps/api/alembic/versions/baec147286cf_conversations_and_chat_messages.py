"""conversations and chat messages

Chat turns already created a `Run` each, but nothing tied them together and the
user's own message was never stored — so a reload lost the thread and the model
started every turn blind.

`chat_messages.trust_tag` is the load-bearing column. A reply that quoted a
scraped page stays `untrusted_external` in the transcript, so replaying history
cannot launder an injection into instruction position by virtue of being old.

The `trust_tag` enum already exists (memories use it), so it is referenced with
`create_type=False`. Letting autogenerate emit a second CREATE TYPE fails on
every database that has ever run a migration.

Revision ID: baec147286cf
Revises: c1a7d3e40b52
Create Date: 2026-08-24 16:34:18.287018
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "baec147286cf"
down_revision: str | Sequence[str] | None = "c1a7d3e40b52"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CHAT_ROLE = postgresql.ENUM("user", "assistant", name="chat_role", create_type=False)
TRUST_TAG = postgresql.ENUM(
    "user_asserted",
    "system_derived",
    "untrusted_external",
    name="trust_tag",
    create_type=False,
)


def upgrade() -> None:
    CHAT_ROLE.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "conversations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_conversations_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conversations")),
    )
    op.create_index(
        "ix_conversations_user_last_message",
        "conversations",
        ["user_id", "last_message_at"],
        unique=False,
    )

    op.create_table(
        "chat_messages",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("conversation_id", sa.UUID(), nullable=False),
        sa.Column("role", CHAT_ROLE, nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=True),
        sa.Column("trust_tag", TRUST_TAG, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name=op.f("fk_chat_messages_conversation_id_conversations"),
            ondelete="CASCADE",
        ),
        # SET NULL rather than CASCADE: pruning old runs must not silently
        # delete the transcript the user is reading.
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["runs.id"],
            name=op.f("fk_chat_messages_run_id_runs"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chat_messages")),
    )
    op.create_index(
        "ix_chat_messages_conversation_created",
        "chat_messages",
        ["conversation_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_chat_messages_conversation_created", table_name="chat_messages")
    op.drop_table("chat_messages")
    op.drop_index("ix_conversations_user_last_message", table_name="conversations")
    op.drop_table("conversations")
    # Owned by this migration, unlike trust_tag.
    CHAT_ROLE.drop(op.get_bind(), checkfirst=True)
