"""add gateway users and per-user telegram settings

Revision ID: 0002_user_settings
Revises: 0001_initial_schema
Create Date: 2026-05-02 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.common import constants

revision: str = "0002_user_settings"
down_revision: Union[str, None] = "0001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _schema() -> str | None:
    return constants.DB_SCHEMA or None


def upgrade() -> None:
    schema = _schema()

    op.create_table(
        "vocabuildary_users",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("identity_key", sa.Text(), nullable=False),
        sa.Column("gateway_sub", sa.Text(), nullable=True),
        sa.Column("email", sa.Text(), nullable=True),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("raw_identity_headers", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("telegram_bot_token", sa.Text(), nullable=True),
        sa.Column("telegram_chat_id", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("identity_key", name="uq_vocabuildary_users_identity_key"),
        schema=schema,
    )

    op.create_index(
        "ix_vocabuildary_users_gateway_sub",
        "vocabuildary_users",
        ["gateway_sub"],
        unique=False,
        schema=schema,
    )
    op.create_index(
        "ix_vocabuildary_users_email",
        "vocabuildary_users",
        ["email"],
        unique=False,
        schema=schema,
    )

    op.add_column(
        "reminder_logs",
        sa.Column("user_id", sa.Integer(), nullable=True),
        schema=schema,
    )
    op.create_foreign_key(
        "fk_reminder_logs_user_id_vocabuildary_users",
        "reminder_logs",
        "vocabuildary_users",
        ["user_id"],
        ["id"],
        source_schema=schema,
        referent_schema=schema,
    )
    op.create_index(
        "ix_reminder_logs_user_id",
        "reminder_logs",
        ["user_id"],
        unique=False,
        schema=schema,
    )


def downgrade() -> None:
    schema = _schema()

    op.drop_index("ix_reminder_logs_user_id", table_name="reminder_logs", schema=schema)
    op.drop_constraint(
        "fk_reminder_logs_user_id_vocabuildary_users",
        "reminder_logs",
        type_="foreignkey",
        schema=schema,
    )
    op.drop_column("reminder_logs", "user_id", schema=schema)
    op.drop_index("ix_vocabuildary_users_email", table_name="vocabuildary_users", schema=schema)
    op.drop_index("ix_vocabuildary_users_gateway_sub", table_name="vocabuildary_users", schema=schema)
    op.drop_table("vocabuildary_users", schema=schema)
