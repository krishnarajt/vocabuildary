"""add dictionary import tracking and word frequency fields

Revision ID: 0005_dictionary_imports
Revises: 0004_learning_progress
Create Date: 2026-05-02 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.common import constants

revision: str = "0005_dictionary_imports"
down_revision: Union[str, None] = "0004_learning_progress"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _schema() -> str | None:
    return constants.DB_SCHEMA or None


def _fk(table_name: str, column_name: str = "id") -> str:
    schema = _schema()
    return f"{schema}.{table_name}.{column_name}" if schema else f"{table_name}.{column_name}"


def upgrade() -> None:
    schema = _schema()

    op.add_column("words", sa.Column("frequency_rank", sa.Integer(), nullable=True), schema=schema)
    op.add_column("words", sa.Column("frequency_score", sa.Float(), nullable=True), schema=schema)
    op.add_column("words", sa.Column("zipf_frequency", sa.Float(), nullable=True), schema=schema)
    op.add_column("words", sa.Column("frequency_source", sa.Text(), nullable=True), schema=schema)
    op.add_column("words", sa.Column("definition_source", sa.Text(), nullable=True), schema=schema)
    op.add_column(
        "words",
        sa.Column("frequency_updated_at", sa.DateTime(timezone=True), nullable=True),
        schema=schema,
    )
    op.add_column(
        "words",
        sa.Column("definition_updated_at", sa.DateTime(timezone=True), nullable=True),
        schema=schema,
    )
    op.create_index(
        "ix_words_language_frequency_rank",
        "words",
        ["language_code", "frequency_rank"],
        unique=False,
        schema=schema,
    )

    op.create_table(
        "dictionary_import_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column(
            "language_code",
            sa.Text(),
            server_default=constants.DEFAULT_TARGET_LANGUAGE_CODE,
            nullable=False,
        ),
        sa.Column("status", sa.Text(), server_default="queued", nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=True),
        sa.Column("chunk_count", sa.Integer(), nullable=True),
        sa.Column("total_items", sa.Integer(), nullable=True),
        sa.Column("processed_items", sa.Integer(), server_default="0", nullable=False),
        sa.Column("inserted_items", sa.Integer(), server_default="0", nullable=False),
        sa.Column("updated_items", sa.Integer(), server_default="0", nullable=False),
        sa.Column("skipped_items", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_by_user_id", sa.Integer(), nullable=True),
        sa.Column("params", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["started_by_user_id"],
            [_fk("vocabuildary_users")],
            name="fk_dictionary_import_runs_started_by_user_id_vocabuildary_users",
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=schema,
    )
    op.create_index(
        "ix_dictionary_import_runs_source_status",
        "dictionary_import_runs",
        ["source", "status"],
        unique=False,
        schema=schema,
    )
    op.create_index(
        "ix_dictionary_import_runs_created_at",
        "dictionary_import_runs",
        ["created_at"],
        unique=False,
        schema=schema,
    )


def downgrade() -> None:
    schema = _schema()

    op.drop_index(
        "ix_dictionary_import_runs_created_at",
        table_name="dictionary_import_runs",
        schema=schema,
    )
    op.drop_index(
        "ix_dictionary_import_runs_source_status",
        table_name="dictionary_import_runs",
        schema=schema,
    )
    op.drop_table("dictionary_import_runs", schema=schema)

    op.drop_index("ix_words_language_frequency_rank", table_name="words", schema=schema)
    op.drop_column("words", "definition_updated_at", schema=schema)
    op.drop_column("words", "frequency_updated_at", schema=schema)
    op.drop_column("words", "definition_source", schema=schema)
    op.drop_column("words", "frequency_source", schema=schema)
    op.drop_column("words", "zipf_frequency", schema=schema)
    op.drop_column("words", "frequency_score", schema=schema)
    op.drop_column("words", "frequency_rank", schema=schema)
