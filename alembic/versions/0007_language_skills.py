"""add language skills, quizzes, and frequency bands

Revision ID: 0007_language_skills
Revises: 0006_catalog_books_and_reminder_slots
Create Date: 2026-05-02 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.common import constants
from app.services.language_skill_service import DEFAULT_FREQUENCY_BANDS, DEFAULT_QUIZZES

revision: str = "0007_language_skills"
down_revision: Union[str, None] = "0006_catalog_books_and_reminder_slots"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


LANGUAGE_NAMES = {
    "en": ("English", "English"),
    "es": ("Spanish", "Espanol"),
    "fr": ("French", "Francais"),
    "de": ("German", "Deutsch"),
    "it": ("Italian", "Italiano"),
    "pt": ("Portuguese", "Portugues"),
    "hi": ("Hindi", "हिन्दी"),
    "ja": ("Japanese", "日本語"),
    "ko": ("Korean", "한국어"),
    "zh": ("Chinese", "中文"),
}


def _schema() -> str | None:
    return constants.DB_SCHEMA or None


def _fk(table_name: str, column_name: str = "id") -> str:
    schema = _schema()
    return f"{schema}.{table_name}.{column_name}" if schema else f"{table_name}.{column_name}"


def _prefix() -> str:
    schema = _schema()
    return f"{schema}." if schema else ""


def upgrade() -> None:
    schema = _schema()

    op.create_table(
        "language_level_frequency_bands",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("language_code", sa.Text(), nullable=False),
        sa.Column("level_code", sa.Text(), nullable=False),
        sa.Column("min_frequency_rank", sa.Integer(), nullable=True),
        sa.Column("max_frequency_rank", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["language_code"],
            [_fk("languages", "code")],
            name="fk_language_level_frequency_bands_language_code_languages",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("language_code", "level_code", name="uq_level_frequency_language_level"),
        schema=schema,
    )
    op.create_index(
        "ix_level_frequency_language_level",
        "language_level_frequency_bands",
        ["language_code", "level_code"],
        unique=False,
        schema=schema,
    )

    op.create_table(
        "language_quizzes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("language_code", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), server_default="default", nullable=False),
        sa.Column("generated_by_model", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["language_code"],
            [_fk("languages", "code")],
            name="fk_language_quizzes_language_code_languages",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            [_fk("vocabuildary_users")],
            name="fk_language_quizzes_created_by_user_id_vocabuildary_users",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("language_code", name="uq_language_quizzes_language_code"),
        schema=schema,
    )

    op.create_table(
        "language_quiz_questions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("quiz_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("prompt_type", sa.Text(), nullable=False),
        sa.Column("question_text", sa.Text(), nullable=False),
        sa.Column("options", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("correct_option_index", sa.Integer(), nullable=False),
        sa.Column("correct_answer", sa.Text(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["quiz_id"],
            [_fk("language_quizzes")],
            name="fk_language_quiz_questions_quiz_id_language_quizzes",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("quiz_id", "position", name="uq_language_quiz_questions_quiz_position"),
        schema=schema,
    )

    op.create_table(
        "user_language_levels",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("language_code", sa.Text(), nullable=False),
        sa.Column("level_code", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), server_default="manual", nullable=False),
        sa.Column("quiz_id", sa.Integer(), nullable=True),
        sa.Column("quiz_score", sa.Integer(), nullable=True),
        sa.Column("quiz_total", sa.Integer(), nullable=True),
        sa.Column("assessed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            [_fk("vocabuildary_users")],
            name="fk_user_language_levels_user_id_vocabuildary_users",
        ),
        sa.ForeignKeyConstraint(
            ["language_code"],
            [_fk("languages", "code")],
            name="fk_user_language_levels_language_code_languages",
        ),
        sa.ForeignKeyConstraint(
            ["quiz_id"],
            [_fk("language_quizzes")],
            name="fk_user_language_levels_quiz_id_language_quizzes",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "language_code", name="uq_user_language_levels_user_language"),
        schema=schema,
    )
    op.create_index(
        "ix_user_language_levels_user_language",
        "user_language_levels",
        ["user_id", "language_code"],
        unique=False,
        schema=schema,
    )

    _seed_languages()
    _seed_frequency_bands()
    _seed_default_quizzes()


def _seed_languages() -> None:
    prefix = _prefix()
    for code in sorted(DEFAULT_QUIZZES):
        name, native_name = LANGUAGE_NAMES.get(code, (code, None))
        op.execute(
            sa.text(
                f"""
                INSERT INTO {prefix}languages (code, name, native_name, notes)
                VALUES (:code, :name, :native_name, :notes)
                ON CONFLICT (code) DO NOTHING
                """
            ).bindparams(
                code=code,
                name=name,
                native_name=native_name,
                notes="Default placement quiz language",
            )
        )


def _seed_frequency_bands() -> None:
    prefix = _prefix()
    for language_code in sorted(DEFAULT_QUIZZES):
        for level_code, (min_rank, max_rank) in DEFAULT_FREQUENCY_BANDS.items():
            op.execute(
                sa.text(
                    f"""
                    INSERT INTO {prefix}language_level_frequency_bands
                        (language_code, level_code, min_frequency_rank, max_frequency_rank)
                    VALUES (:language_code, :level_code, :min_rank, :max_rank)
                    ON CONFLICT (language_code, level_code) DO NOTHING
                    """
                ).bindparams(
                    language_code=language_code,
                    level_code=level_code,
                    min_rank=min_rank,
                    max_rank=max_rank,
                )
            )


def _seed_default_quizzes() -> None:
    schema = _schema()
    metadata = sa.MetaData()
    quizzes = sa.Table(
        "language_quizzes",
        metadata,
        sa.Column("id", sa.Integer()),
        sa.Column("language_code", sa.Text()),
        sa.Column("title", sa.Text()),
        sa.Column("source", sa.Text()),
        schema=schema,
    )
    questions = sa.Table(
        "language_quiz_questions",
        metadata,
        sa.Column("quiz_id", sa.Integer()),
        sa.Column("position", sa.Integer()),
        sa.Column("prompt_type", sa.Text()),
        sa.Column("question_text", sa.Text()),
        sa.Column("options", sa.JSON()),
        sa.Column("correct_option_index", sa.Integer()),
        sa.Column("correct_answer", sa.Text()),
        schema=schema,
    )
    connection = op.get_bind()
    for language_code, quiz_questions in DEFAULT_QUIZZES.items():
        language_name, _native_name = LANGUAGE_NAMES.get(language_code, (language_code, None))
        result = connection.execute(
            quizzes.insert().values(
                language_code=language_code,
                title=f"{language_name} Placement Quiz",
                source="default",
            )
        )
        quiz_id = result.inserted_primary_key[0]
        connection.execute(
            questions.insert(),
            [
                {
                    "quiz_id": quiz_id,
                    "position": index,
                    "prompt_type": question["type"],
                    "question_text": question["question"],
                    "options": question["options"],
                    "correct_option_index": question["options"].index(question["answer"]),
                    "correct_answer": question["answer"],
                }
                for index, question in enumerate(quiz_questions, start=1)
            ],
        )


def downgrade() -> None:
    schema = _schema()

    op.drop_index(
        "ix_user_language_levels_user_language",
        table_name="user_language_levels",
        schema=schema,
    )
    op.drop_table("user_language_levels", schema=schema)
    op.drop_table("language_quiz_questions", schema=schema)
    op.drop_table("language_quizzes", schema=schema)
    op.drop_index(
        "ix_level_frequency_language_level",
        table_name="language_level_frequency_bands",
        schema=schema,
    )
    op.drop_table("language_level_frequency_bands", schema=schema)
