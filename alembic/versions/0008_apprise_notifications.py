"""add apprise notification settings

Revision ID: 0008_apprise_notifications
Revises: 0007_language_skills
Create Date: 2026-05-02 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.common import constants

revision: str = "0008_apprise_notifications"
down_revision: Union[str, None] = "0007_language_skills"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _schema() -> str | None:
    return constants.DB_SCHEMA or None


def upgrade() -> None:
    schema = _schema()

    op.add_column(
        "vocabuildary_users",
        sa.Column(
            "notification_provider",
            sa.Text(),
            server_default="telegram",
            nullable=False,
        ),
        schema=schema,
    )
    op.add_column(
        "vocabuildary_users",
        sa.Column("apprise_urls", sa.Text(), nullable=True),
        schema=schema,
    )


def downgrade() -> None:
    schema = _schema()

    op.drop_column("vocabuildary_users", "apprise_urls", schema=schema)
    op.drop_column("vocabuildary_users", "notification_provider", schema=schema)
