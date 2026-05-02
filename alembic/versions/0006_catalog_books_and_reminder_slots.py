"""add language catalog, book words, and reminder slots

Revision ID: 0006_catalog_books_and_reminder_slots
Revises: 0005_dictionary_imports
Create Date: 2026-05-02 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.common import constants

revision: str = "0006_catalog_books_and_reminder_slots"
down_revision: Union[str, None] = "0005_dictionary_imports"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _schema() -> str | None:
    return constants.DB_SCHEMA or None


def _fk(table_name: str, column_name: str = "id") -> str:
    schema = _schema()
    return f"{schema}.{table_name}.{column_name}" if schema else f"{table_name}.{column_name}"


def upgrade() -> None:
    schema = _schema()

    op.create_table(
        "languages",
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("native_name", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("code"),
        schema=schema,
    )
    op.execute(
        sa.text(
            f"""
            INSERT INTO {schema + '.' if schema else ''}languages (code, name, native_name, notes)
            VALUES (:code, :name, :native_name, :notes)
            ON CONFLICT (code) DO NOTHING
            """
        ).bindparams(
            code=constants.DEFAULT_TARGET_LANGUAGE_CODE,
            name="English" if constants.DEFAULT_TARGET_LANGUAGE_CODE == "en" else constants.DEFAULT_TARGET_LANGUAGE_CODE,
            native_name="English" if constants.DEFAULT_TARGET_LANGUAGE_CODE == "en" else None,
            notes="Default language",
        )
    )

    op.add_column(
        "books",
        sa.Column(
            "language_code",
            sa.Text(),
            server_default=constants.DEFAULT_TARGET_LANGUAGE_CODE,
            nullable=False,
        ),
        schema=schema,
    )
    op.add_column(
        "books",
        sa.Column("learning_enabled", sa.Boolean(), server_default="false", nullable=False),
        schema=schema,
    )
    op.create_index(
        "ix_books_user_learning",
        "books",
        ["user_id", "learning_enabled"],
        unique=False,
        schema=schema,
    )

    op.create_table(
        "book_words",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("book_id", sa.Integer(), nullable=False),
        sa.Column("word_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column(
            "language_code",
            sa.Text(),
            server_default=constants.DEFAULT_TARGET_LANGUAGE_CODE,
            nullable=False,
        ),
        sa.Column("source_text", sa.Text(), nullable=False),
        sa.Column("occurrence_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("rank_in_book", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["book_id"], [_fk("books")], name="fk_book_words_book_id_books"),
        sa.ForeignKeyConstraint(["word_id"], [_fk("words")], name="fk_book_words_word_id_words"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            [_fk("vocabuildary_users")],
            name="fk_book_words_user_id_vocabuildary_users",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("book_id", "word_id", name="uq_book_words_book_word"),
        schema=schema,
    )
    op.create_index(
        "ix_book_words_user_language_rank",
        "book_words",
        ["user_id", "language_code", "rank_in_book"],
        unique=False,
        schema=schema,
    )
    op.create_index(
        "ix_book_words_book_rank",
        "book_words",
        ["book_id", "rank_in_book"],
        unique=False,
        schema=schema,
    )

    op.create_table(
        "user_reminder_slots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("label", sa.Text(), nullable=True),
        sa.Column("time_of_day", sa.Text(), nullable=False),
        sa.Column("timezone", sa.Text(), server_default=constants.TZ, nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("last_sent_on", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            [_fk("vocabuildary_users")],
            name="fk_user_reminder_slots_user_id_vocabuildary_users",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "time_of_day", name="uq_user_reminder_slots_user_time"),
        schema=schema,
    )
    op.create_index(
        "ix_user_reminder_slots_due",
        "user_reminder_slots",
        ["enabled", "time_of_day", "last_sent_on"],
        unique=False,
        schema=schema,
    )


def downgrade() -> None:
    schema = _schema()

    op.drop_index("ix_user_reminder_slots_due", table_name="user_reminder_slots", schema=schema)
    op.drop_table("user_reminder_slots", schema=schema)

    op.drop_index("ix_book_words_book_rank", table_name="book_words", schema=schema)
    op.drop_index("ix_book_words_user_language_rank", table_name="book_words", schema=schema)
    op.drop_table("book_words", schema=schema)

    op.drop_index("ix_books_user_learning", table_name="books", schema=schema)
    op.drop_column("books", "learning_enabled", schema=schema)
    op.drop_column("books", "language_code", schema=schema)

    op.drop_table("languages", schema=schema)
