"""
Alembic environment configuration.

Uses the same DATABASE_URL, DB_SCHEMA, and SQLAlchemy metadata as the app.
"""

from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool, text

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.common import constants  # noqa: E402
from app.db.database import Base  # noqa: E402
from app.db import models  # noqa: F401,E402

config = context.config
config.set_main_option("sqlalchemy.url", constants.DATABASE_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _version_table_schema() -> str | None:
    return None if constants.DB_SCHEMA == "public" else constants.DB_SCHEMA


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_schemas=True,
        version_table_schema=_version_table_schema(),
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        if constants.DB_SCHEMA and constants.DB_SCHEMA != "public":
            connection.execute(
                text(f'CREATE SCHEMA IF NOT EXISTS "{constants.DB_SCHEMA}"')
            )
            connection.commit()

        def include_object(object, name, type_, reflected, compare_to):
            if hasattr(object, "schema"):
                return object.schema == constants.DB_SCHEMA
            return True

        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_schemas=True,
            version_table_schema=_version_table_schema(),
            include_object=include_object,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
