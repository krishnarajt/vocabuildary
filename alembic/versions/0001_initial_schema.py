"""baseline existing schema

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-05-02 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy import inspect

from app.common import constants

revision: str = "0001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    schema = constants.DB_SCHEMA or None
    if schema and schema != "public":
        op.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')

    if context.is_offline_mode():
        _create_initial_tables(schema)
        return

    inspector = inspect(bind)

    if not inspector.has_table("words", schema=schema):
        _create_words_table(schema)

    if not inspector.has_table("reminder_logs", schema=schema):
        _create_reminder_logs_table(schema)


def _create_initial_tables(schema: str | None) -> None:
    _create_words_table(schema)
    _create_reminder_logs_table(schema)


def _create_words_table(schema: str | None) -> None:
    op.create_table(
        "words",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("word", sa.Text(), nullable=False),
        sa.Column("meaning", sa.Text(), nullable=False),
        sa.Column("example", sa.Text(), nullable=False),
        sa.Column("sent", sa.Boolean(), server_default="false", nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("word", name="uq_words_word"),
        schema=schema,
    )


def _create_reminder_logs_table(schema: str | None) -> None:
    op.create_table(
        "reminder_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("word_id", sa.Integer(), nullable=False),
        sa.Column("word_text", sa.Text(), nullable=False),
        sa.Column(
            "reminded_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["word_id"],
            [f"{schema}.words.id" if schema else "words.id"],
            name="fk_reminder_logs_word_id_words",
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=schema,
    )


def downgrade() -> None:
    # Intentionally non-destructive: this baseline may be run against a live
    # database that already contains vocabulary/reminder history.
    pass
