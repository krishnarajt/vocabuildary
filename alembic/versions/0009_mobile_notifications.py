"""add mobile devices and notification queue

Revision ID: 0009_mobile_notifications
Revises: 0008_apprise_notifications
Create Date: 2026-05-02 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.common import constants

revision: str = "0009_mobile_notifications"
down_revision: Union[str, None] = "0008_apprise_notifications"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _schema() -> str | None:
    return constants.DB_SCHEMA or None


def _fk(target: str) -> str:
    schema = _schema()
    return f"{schema}.{target}" if schema else target


def upgrade() -> None:
    schema = _schema()

    op.create_table(
        "mobile_devices",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("device_id", sa.Text(), nullable=False),
        sa.Column("platform", sa.Text(), server_default="android", nullable=False),
        sa.Column("display_name", sa.Text(), nullable=True),
        sa.Column("push_token", sa.Text(), nullable=True),
        sa.Column("timezone", sa.Text(), server_default=constants.TZ, nullable=False),
        sa.Column("app_version", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], [f"{_fk('vocabuildary_users')}.id"]),
        sa.UniqueConstraint("user_id", "device_id", name="uq_mobile_devices_user_device"),
        schema=schema,
    )

    op.create_table(
        "mobile_notifications",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("device_id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=True),
        sa.Column("word_id", sa.Integer(), nullable=True),
        sa.Column("notification_kind", sa.Text(), server_default="daily", nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("html_body", sa.Text(), nullable=True),
        sa.Column("metadata", sa.JSON(), server_default="{}", nullable=False),
        sa.Column(
            "queued_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], [f"{_fk('vocabuildary_users')}.id"]),
        sa.ForeignKeyConstraint(["device_id"], [f"{_fk('mobile_devices')}.id"]),
        sa.ForeignKeyConstraint(["session_id"], [f"{_fk('daily_learning_sessions')}.id"]),
        sa.ForeignKeyConstraint(["word_id"], [f"{_fk('words')}.id"]),
        schema=schema,
    )
    op.create_index(
        "ix_mobile_notifications_user_pending",
        "mobile_notifications",
        ["user_id", "delivered_at", "queued_at"],
        schema=schema,
    )


def downgrade() -> None:
    schema = _schema()

    op.drop_index(
        "ix_mobile_notifications_user_pending",
        table_name="mobile_notifications",
        schema=schema,
    )
    op.drop_table("mobile_notifications", schema=schema)
    op.drop_table("mobile_devices", schema=schema)
