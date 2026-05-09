"""add mobile auth tokens

Revision ID: 0010_mobile_auth_tokens
Revises: 0009_mobile_notifications
Create Date: 2026-05-09
"""

from typing import Union

import sqlalchemy as sa
from alembic import op

from app.common import constants

revision: str = "0010_mobile_auth_tokens"
down_revision: Union[str, None] = "0009_mobile_notifications"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def _fk(table: str, column: str = "id") -> str:
    if constants.DB_SCHEMA:
        return f"{constants.DB_SCHEMA}.{table}.{column}"
    return f"{table}.{column}"


def upgrade() -> None:
    schema = constants.DB_SCHEMA or None
    op.create_table(
        "mobile_auth_tokens",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("device_id", sa.Text(), nullable=True),
        sa.Column("label", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            [_fk("vocabuildary_users")],
            name="fk_mobile_auth_tokens_user_id_vocabuildary_users",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_mobile_auth_tokens_token_hash"),
        schema=schema,
    )
    op.create_index(
        "ix_mobile_auth_tokens_user_id",
        "mobile_auth_tokens",
        ["user_id"],
        schema=schema,
    )


def downgrade() -> None:
    schema = constants.DB_SCHEMA or None
    op.drop_index("ix_mobile_auth_tokens_user_id", table_name="mobile_auth_tokens", schema=schema)
    op.drop_table("mobile_auth_tokens", schema=schema)
