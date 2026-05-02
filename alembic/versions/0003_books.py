"""add uploaded books and processed word maps

Revision ID: 0003_books
Revises: 0002_user_settings
Create Date: 2026-05-02 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.common import constants

revision: str = "0003_books"
down_revision: Union[str, None] = "0002_user_settings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _schema() -> str | None:
    return constants.DB_SCHEMA or None


def upgrade() -> None:
    schema = _schema()

    op.create_table(
        "books",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("book_uuid", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("isbn", sa.Text(), nullable=True),
        sa.Column("author", sa.Text(), nullable=True),
        sa.Column("language", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("original_filename", sa.Text(), nullable=False),
        sa.Column("file_extension", sa.Text(), nullable=False),
        sa.Column("mime_type", sa.Text(), nullable=True),
        sa.Column("file_size", sa.Integer(), nullable=True),
        sa.Column("source_bucket", sa.Text(), nullable=False),
        sa.Column("source_object_key", sa.Text(), nullable=False),
        sa.Column("word_map_bucket", sa.Text(), nullable=True),
        sa.Column("word_map_object_key", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), server_default="upload_pending", nullable=False),
        sa.Column("processing_error", sa.Text(), nullable=True),
        sa.Column("total_words", sa.Integer(), nullable=True),
        sa.Column("unique_words", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            [f"{schema}.vocabuildary_users.id" if schema else "vocabuildary_users.id"],
            name="fk_books_user_id_vocabuildary_users",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("book_uuid", name="uq_books_book_uuid"),
        schema=schema,
    )
    op.create_index("ix_books_user_id", "books", ["user_id"], unique=False, schema=schema)
    op.create_index("ix_books_status", "books", ["status"], unique=False, schema=schema)


def downgrade() -> None:
    schema = _schema()

    op.drop_index("ix_books_status", table_name="books", schema=schema)
    op.drop_index("ix_books_user_id", table_name="books", schema=schema)
    op.drop_table("books", schema=schema)
