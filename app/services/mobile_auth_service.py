"""Gateway-authenticated mobile token handoff."""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common import constants
from app.db.models import MobileAuthToken, VocabuildaryUser

TOKEN_PREFIX = "vbt_"


class MobileAuthError(ValueError):
    """Raised when a mobile auth request is not valid."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def bearer_token_from_headers(headers: Mapping[str, str]) -> str | None:
    for key, value in headers.items():
        if key.lower() != "authorization":
            continue
        parts = value.strip().split(" ", 1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            token = parts[1].strip()
            return token or None
    return None


def issue_mobile_auth_token(
    db: Session,
    user: VocabuildaryUser,
    *,
    device_id: str | None = None,
    label: str | None = None,
) -> str:
    """Create a bearer token for a user already authenticated by the gateway."""
    token = f"{TOKEN_PREFIX}{secrets.token_urlsafe(32)}"
    expires_at = None
    if constants.MOBILE_AUTH_TOKEN_TTL_DAYS > 0:
        expires_at = _utc_now() + timedelta(days=constants.MOBILE_AUTH_TOKEN_TTL_DAYS)

    db.add(
        MobileAuthToken(
            user_id=user.id,
            token_hash=_hash_token(token),
            device_id=(device_id or "").strip() or None,
            label=(label or "").strip() or None,
            expires_at=expires_at,
        )
    )
    db.commit()
    return token


def user_for_mobile_auth_token(
    db: Session,
    token: str | None,
) -> VocabuildaryUser | None:
    """Resolve a mobile bearer token to its user, returning None for misses."""
    if not token or not token.startswith(TOKEN_PREFIX):
        return None

    now = _utc_now()
    row = db.execute(
        select(MobileAuthToken)
        .where(MobileAuthToken.token_hash == _hash_token(token))
        .where(MobileAuthToken.revoked_at.is_(None))
        .limit(1)
    ).scalar_one_or_none()
    if row is None:
        return None
    if row.expires_at is not None:
        expires_at = row.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= now:
            return None

    row.last_used_at = now
    row.user.last_seen_at = now
    db.commit()
    return row.user


def revoke_mobile_auth_token(db: Session, token: str | None) -> bool:
    if not token or not token.startswith(TOKEN_PREFIX):
        return False
    row = db.execute(
        select(MobileAuthToken)
        .where(MobileAuthToken.token_hash == _hash_token(token))
        .where(MobileAuthToken.revoked_at.is_(None))
        .limit(1)
    ).scalar_one_or_none()
    if row is None:
        return False
    row.revoked_at = _utc_now()
    db.commit()
    return True
