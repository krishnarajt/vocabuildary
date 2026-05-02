"""
Alembic environment configuration.

Uses the same DATABASE_URL, DB_SCHEMA, and SQLAlchemy metadata as the app.
"""

from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import (
    Column,
    MetaData,
    PrimaryKeyConstraint,
    String,
    Table,
    engine_from_config,
    pool,
    text,
)

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

ALEMBIC_VERSION_NUM_LENGTH = 128


def _version_table_schema() -> str | None:
    if not constants.DB_SCHEMA or constants.DB_SCHEMA == "public":
        return None
    return constants.DB_SCHEMA


def _ensure_version_table_capacity(connection) -> None:
    """
    Alembic creates version_num as VARCHAR(32) by default, but this project
    uses descriptive revision IDs such as 0006_catalog_books_and_reminder_slots.
    Prepare/widen the table before Alembic writes the next revision marker.
    """
    schema = _version_table_schema()
    version_table = Table(
        "alembic_version",
        MetaData(),
        Column("version_num", String(ALEMBIC_VERSION_NUM_LENGTH), nullable=False),
        PrimaryKeyConstraint("version_num", name="alembic_version_pkc"),
        schema=schema,
    )
    version_table.create(connection, checkfirst=True)

    if connection.dialect.name != "postgresql":
        return

    schema_name = schema
    if schema_name is None:
        schema_name = connection.execute(text("SELECT current_schema()")).scalar_one()

    column_info = (
        connection.execute(
            text(
                """
                SELECT data_type, character_maximum_length
                FROM information_schema.columns
                WHERE table_schema = :schema_name
                  AND table_name = 'alembic_version'
                  AND column_name = 'version_num'
                """
            ),
            {"schema_name": schema_name},
        )
        .mappings()
        .first()
    )
    if not column_info:
        return

    current_length = column_info["character_maximum_length"]
    if column_info["data_type"] == "character varying" and (
        current_length is not None and current_length < ALEMBIC_VERSION_NUM_LENGTH
    ):
        preparer = connection.dialect.identifier_preparer
        connection.execute(
            text(
                "ALTER TABLE "
                f"{preparer.format_table(version_table)} "
                f"ALTER COLUMN {preparer.quote('version_num')} "
                f"TYPE VARCHAR({ALEMBIC_VERSION_NUM_LENGTH})"
            )
        )


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

        _ensure_version_table_capacity(connection)
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
