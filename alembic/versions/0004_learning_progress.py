"""add per-user learning progress and exposure scheduling

Revision ID: 0004_learning_progress
Revises: 0003_books
Create Date: 2026-05-02 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.common import constants

revision: str = "0004_learning_progress"
down_revision: Union[str, None] = "0003_books"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _schema() -> str | None:
    return constants.DB_SCHEMA or None


def _fk(table_name: str, column_name: str = "id") -> str:
    schema = _schema()
    return f"{schema}.{table_name}.{column_name}" if schema else f"{table_name}.{column_name}"


def upgrade() -> None:
    schema = _schema()

    op.add_column(
        "words",
        sa.Column(
            "language_code",
            sa.Text(),
            server_default=constants.DEFAULT_TARGET_LANGUAGE_CODE,
            nullable=False,
        ),
        schema=schema,
    )
    op.add_column("words", sa.Column("part_of_speech", sa.Text(), nullable=True), schema=schema)
    op.add_column("words", sa.Column("pronunciation", sa.Text(), nullable=True), schema=schema)
    op.add_column("words", sa.Column("origin_language", sa.Text(), nullable=True), schema=schema)
    op.add_column("words", sa.Column("etymology", sa.Text(), nullable=True), schema=schema)
    op.add_column("words", sa.Column("register", sa.Text(), nullable=True), schema=schema)
    op.add_column("words", sa.Column("difficulty_level", sa.Integer(), nullable=True), schema=schema)
    op.add_column(
        "words",
        sa.Column("metadata", sa.JSON(), server_default="{}", nullable=False),
        schema=schema,
    )
    op.drop_constraint("uq_words_word", "words", type_="unique", schema=schema)
    op.create_unique_constraint(
        "uq_words_language_word",
        "words",
        ["language_code", "word"],
        schema=schema,
    )
    op.create_index(
        "ix_words_language_code",
        "words",
        ["language_code"],
        unique=False,
        schema=schema,
    )

    op.create_table(
        "user_learning_settings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "target_language_code",
            sa.Text(),
            server_default=constants.DEFAULT_TARGET_LANGUAGE_CODE,
            nullable=False,
        ),
        sa.Column(
            "daily_review_words",
            sa.Integer(),
            server_default=str(constants.DEFAULT_DAILY_REVIEW_WORDS),
            nullable=False,
        ),
        sa.Column(
            "daily_cloze_words",
            sa.Integer(),
            server_default=str(constants.DEFAULT_DAILY_CLOZE_WORDS),
            nullable=False,
        ),
        sa.Column(
            "mastery_encounters",
            sa.Integer(),
            server_default=str(constants.DEFAULT_MASTERY_ENCOUNTERS),
            nullable=False,
        ),
        sa.Column(
            "review_intervals",
            sa.JSON(),
            server_default=str(constants.DEFAULT_REVIEW_INTERVAL_DAYS).replace(" ", ""),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            [_fk("vocabuildary_users")],
            name="fk_user_learning_settings_user_id_vocabuildary_users",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_user_learning_settings_user_id"),
        schema=schema,
    )

    op.create_table(
        "user_word_progress",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("word_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), server_default="learning", nullable=False),
        sa.Column("introduced_on", sa.Date(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_on", sa.Date(), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_due_on", sa.Date(), nullable=True),
        sa.Column("encounter_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("context_encounter_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("cloze_prompt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("cloze_answer_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("schedule_step", sa.Integer(), server_default="0", nullable=False),
        sa.Column("interval_days", sa.Integer(), server_default="0", nullable=False),
        sa.Column("progress_percent", sa.Integer(), server_default="0", nullable=False),
        sa.Column("mastered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reset_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            [_fk("vocabuildary_users")],
            name="fk_user_word_progress_user_id_vocabuildary_users",
        ),
        sa.ForeignKeyConstraint(
            ["word_id"],
            [_fk("words")],
            name="fk_user_word_progress_word_id_words",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "word_id", name="uq_user_word_progress_user_word"),
        schema=schema,
    )
    op.create_index(
        "ix_user_word_progress_user_due",
        "user_word_progress",
        ["user_id", "next_due_on"],
        unique=False,
        schema=schema,
    )
    op.create_index(
        "ix_user_word_progress_user_progress",
        "user_word_progress",
        ["user_id", "progress_percent"],
        unique=False,
        schema=schema,
    )

    op.create_table(
        "daily_learning_sessions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("session_date", sa.Date(), nullable=False),
        sa.Column("new_word_id", sa.Integer(), nullable=False),
        sa.Column("cloze_word_id", sa.Integer(), nullable=True),
        sa.Column("previous_cloze_session_id", sa.Integer(), nullable=True),
        sa.Column("previous_cloze_word_id", sa.Integer(), nullable=True),
        sa.Column("reminder_word_ids", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("context_word_ids", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("generated_content", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("cloze_prompt", sa.Text(), nullable=True),
        sa.Column("cloze_answer", sa.Text(), nullable=True),
        sa.Column("message_text", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cloze_answer_revealed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            [_fk("vocabuildary_users")],
            name="fk_daily_learning_sessions_user_id_vocabuildary_users",
        ),
        sa.ForeignKeyConstraint(
            ["new_word_id"],
            [_fk("words")],
            name="fk_daily_learning_sessions_new_word_id_words",
        ),
        sa.ForeignKeyConstraint(
            ["cloze_word_id"],
            [_fk("words")],
            name="fk_daily_learning_sessions_cloze_word_id_words",
        ),
        sa.ForeignKeyConstraint(
            ["previous_cloze_session_id"],
            [_fk("daily_learning_sessions")],
            name="fk_daily_learning_sessions_previous_cloze_session_id",
        ),
        sa.ForeignKeyConstraint(
            ["previous_cloze_word_id"],
            [_fk("words")],
            name="fk_daily_learning_sessions_previous_cloze_word_id_words",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "session_date", name="uq_daily_learning_sessions_user_date"),
        schema=schema,
    )
    op.create_index(
        "ix_daily_learning_sessions_user_date",
        "daily_learning_sessions",
        ["user_id", "session_date"],
        unique=False,
        schema=schema,
    )

    op.create_table(
        "user_word_exposures",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("word_id", sa.Integer(), nullable=False),
        sa.Column("progress_id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("exposure_date", sa.Date(), nullable=False),
        sa.Column("exposure_kind", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            [_fk("vocabuildary_users")],
            name="fk_user_word_exposures_user_id_vocabuildary_users",
        ),
        sa.ForeignKeyConstraint(
            ["word_id"],
            [_fk("words")],
            name="fk_user_word_exposures_word_id_words",
        ),
        sa.ForeignKeyConstraint(
            ["progress_id"],
            [_fk("user_word_progress")],
            name="fk_user_word_exposures_progress_id_user_word_progress",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            [_fk("daily_learning_sessions")],
            name="fk_user_word_exposures_session_id_daily_learning_sessions",
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=schema,
    )
    op.create_index(
        "ix_user_word_exposures_user_word",
        "user_word_exposures",
        ["user_id", "word_id"],
        unique=False,
        schema=schema,
    )
    op.create_index(
        "ix_user_word_exposures_user_date",
        "user_word_exposures",
        ["user_id", "exposure_date"],
        unique=False,
        schema=schema,
    )


def downgrade() -> None:
    schema = _schema()

    op.drop_index("ix_user_word_exposures_user_date", table_name="user_word_exposures", schema=schema)
    op.drop_index("ix_user_word_exposures_user_word", table_name="user_word_exposures", schema=schema)
    op.drop_table("user_word_exposures", schema=schema)

    op.drop_index(
        "ix_daily_learning_sessions_user_date",
        table_name="daily_learning_sessions",
        schema=schema,
    )
    op.drop_table("daily_learning_sessions", schema=schema)

    op.drop_index(
        "ix_user_word_progress_user_progress",
        table_name="user_word_progress",
        schema=schema,
    )
    op.drop_index(
        "ix_user_word_progress_user_due",
        table_name="user_word_progress",
        schema=schema,
    )
    op.drop_table("user_word_progress", schema=schema)

    op.drop_table("user_learning_settings", schema=schema)

    op.drop_index("ix_words_language_code", table_name="words", schema=schema)
    op.drop_constraint("uq_words_language_word", "words", type_="unique", schema=schema)
    op.create_unique_constraint("uq_words_word", "words", ["word"], schema=schema)
    op.drop_column("words", "metadata", schema=schema)
    op.drop_column("words", "difficulty_level", schema=schema)
    op.drop_column("words", "register", schema=schema)
    op.drop_column("words", "etymology", schema=schema)
    op.drop_column("words", "origin_language", schema=schema)
    op.drop_column("words", "pronunciation", schema=schema)
    op.drop_column("words", "part_of_speech", schema=schema)
    op.drop_column("words", "language_code", schema=schema)
