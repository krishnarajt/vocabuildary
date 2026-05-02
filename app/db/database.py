"""
SQLAlchemy engine + session + init_db.
Same shape as LLMGateway's app/db/database.py.
"""

import logging
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.orm import declarative_base, sessionmaker, Session

from app.common import constants

logger = logging.getLogger(__name__)

# ---- Engine ----
# pool_pre_ping so long-idle pods don't explode on a stale connection
engine = create_engine(
    constants.DATABASE_URL,
    pool_pre_ping=True,
    future=True,
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
    if constants.DB_SCHEMA and constants.DB_SCHEMA != "public":
        connection.exec_driver_sql(
            f'CREATE SCHEMA IF NOT EXISTS "{constants.DB_SCHEMA}"'
        )


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
    if use_alembic:
        from alembic import command
        from alembic.config import Config

        alembic_cfg = Config("alembic.ini")
        command.upgrade(alembic_cfg, "head")
        logger.info("Database migrated via Alembic")
    else:
        Base.metadata.create_all(bind=engine)
        logger.info("Database tables created via create_all()")

    inspector = inspect(engine)
    words_exists = inspector.has_table("words", schema=constants.DB_SCHEMA or None)
    logger.info(
        "Database initialized. words table present=%s in schema=%r",
        words_exists,
        constants.DB_SCHEMA,
    )
