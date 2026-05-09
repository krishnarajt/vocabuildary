"""
SQLAlchemy engine + session + init_db.
Same shape as LLMGateway's app/db/database.py.
"""

import logging
from sqlalchemy import create_engine, event, inspect, select
from sqlalchemy.orm import declarative_base, sessionmaker, Session

from app.common import constants

logger = logging.getLogger(__name__)

# ---- Engine ----
# pool_pre_ping so long-idle pods don't explode on a stale connection
_engine_kwargs = {
    "pool_pre_ping": True,
    "future": True,
}
if constants.DATABASE_URL.startswith("sqlite"):
    # The built-in HTTP server handles requests on worker threads.
    _engine_kwargs["connect_args"] = {"check_same_thread": False}

engine = create_engine(
    constants.DATABASE_URL,
    **_engine_kwargs,
)

# ---- Session ----
SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
    future=True,
)

# ---- Declarative base ----
# Pin all tables to the configured schema so a single Postgres can host
# multiple apps cleanly (LLMGateway + Vocabuildary + future stuff).
Base = declarative_base(metadata=None)


def _safe_database_url() -> str:
    """Redact the password before logging the configured database URL."""
    try:
        return engine.url.render_as_string(hide_password=True)
    except Exception:
        return "<unavailable>"


@event.listens_for(Base.metadata, "before_create")
def _ensure_schema(target, connection, **kw):
    """Create the target schema if it doesn't exist yet."""
    if (
        connection.dialect.name == "postgresql"
        and constants.DB_SCHEMA
        and constants.DB_SCHEMA != "public"
    ):
        connection.exec_driver_sql(
            f'CREATE SCHEMA IF NOT EXISTS "{constants.DB_SCHEMA}"'
        )


def _schema_for_inspection() -> str | None:
    if engine.dialect.name == "sqlite":
        return None
    return constants.DB_SCHEMA or None


def get_db() -> Session:
    """Yield a session, ensuring close. Use with `with get_db_session()`."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_db_session() -> Session:
    """Simple factory for jobs (non-generator) — caller must close."""
    return SessionLocal()


def init_db(use_alembic: bool = False) -> None:
    """
    Initialize the database.

    Production startup should pass use_alembic=True so every schema change is
    applied through versioned migrations. create_all() remains as a quick local
    fallback for ad-hoc development only.
    """
    # Import models so they register with Base.metadata before create_all.
    from app.db import models  # noqa: F401

    logger.info(
        "Initializing database tables at %s (schema=%r)...",
        _safe_database_url(),
        constants.DB_SCHEMA,
    )
    should_use_alembic = use_alembic and engine.dialect.name != "sqlite"
    if should_use_alembic:
        from alembic import command
        from alembic.config import Config

        alembic_cfg = Config("alembic.ini")
        command.upgrade(alembic_cfg, "head")
        logger.info("Database migrated via Alembic")
    else:
        Base.metadata.create_all(bind=engine)
        logger.info("Database tables created via create_all()")
        _seed_create_all_reference_data()

    inspector = inspect(engine)
    words_exists = inspector.has_table("words", schema=_schema_for_inspection())
    logger.info(
        "Database initialized. words table present=%s in schema=%r",
        words_exists,
        constants.DB_SCHEMA,
    )


def _seed_create_all_reference_data() -> None:
    """Seed reference rows normally inserted by Alembic data migrations."""
    from app.db.models import (
        Language,
        LanguageLevelFrequencyBand,
        LanguageQuiz,
        LanguageQuizQuestion,
    )
    from app.services.catalog_service import language_name_from_code
    from app.services.language_skill_service import DEFAULT_FREQUENCY_BANDS, DEFAULT_QUIZZES

    db = SessionLocal()
    try:
        for language_code in sorted(DEFAULT_QUIZZES):
            if db.get(Language, language_code) is None:
                name = language_name_from_code(language_code)
                db.add(
                    Language(
                        code=language_code,
                        name=name,
                        native_name=name,
                        notes="Default placement quiz language",
                    )
                )
        db.flush()

        for language_code in sorted(DEFAULT_QUIZZES):
            for level_code, (min_rank, max_rank) in DEFAULT_FREQUENCY_BANDS.items():
                exists = db.execute(
                    select(LanguageLevelFrequencyBand.id).where(
                        LanguageLevelFrequencyBand.language_code == language_code,
                        LanguageLevelFrequencyBand.level_code == level_code,
                    )
                ).scalar_one_or_none()
                if exists is None:
                    db.add(
                        LanguageLevelFrequencyBand(
                            language_code=language_code,
                            level_code=level_code,
                            min_frequency_rank=min_rank,
                            max_frequency_rank=max_rank,
                        )
                    )
        db.flush()

        for language_code, quiz_questions in sorted(DEFAULT_QUIZZES.items()):
            existing_quiz_id = db.execute(
                select(LanguageQuiz.id).where(LanguageQuiz.language_code == language_code)
            ).scalar_one_or_none()
            if existing_quiz_id is not None:
                continue

            language_name = language_name_from_code(language_code)
            quiz = LanguageQuiz(
                language_code=language_code,
                title=f"{language_name} Placement Quiz",
                source="default",
            )
            db.add(quiz)
            db.flush()

            db.add_all(
                [
                    LanguageQuizQuestion(
                        quiz_id=quiz.id,
                        position=index,
                        prompt_type=question["type"],
                        question_text=question["question"],
                        options=question["options"],
                        correct_option_index=question["options"].index(question["answer"]),
                        correct_answer=question["answer"],
                    )
                    for index, question in enumerate(quiz_questions, start=1)
                ]
            )

        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
