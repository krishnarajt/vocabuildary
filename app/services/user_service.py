"""User settings and identity persistence for Vocabuildary."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common import constants
from app.db.models import UserLearningSettings, VocabuildaryUser
from app.services.header_identity import GatewayIdentity


def _redact_token(token: str | None) -> str | None:
    if not token:
        return None
    if len(token) <= 8:
        return "saved"
    return f"{token[:4]}...{token[-4:]}"


def get_or_create_user(db: Session, identity: GatewayIdentity) -> VocabuildaryUser:
    """Upsert the user row from trusted gateway identity headers."""
    stmt = select(VocabuildaryUser).where(
        VocabuildaryUser.identity_key == identity.identity_key
    )
    user = db.execute(stmt).scalar_one_or_none()
    now = datetime.now(timezone.utc)

    if user is None:
        user = VocabuildaryUser(identity_key=identity.identity_key)
        db.add(user)

    user.gateway_sub = identity.sub
    user.email = identity.email
    user.name = identity.name
    user.raw_identity_headers = identity.raw_headers
    user.last_seen_at = now
    user.updated_at = now
    if user.learning_settings is None:
        user.learning_settings = UserLearningSettings()

    db.commit()
    db.refresh(user)
    return user


def get_or_create_learning_settings(
    db: Session,
    user: VocabuildaryUser,
) -> UserLearningSettings:
    """Ensure a user has a row of learning cadence settings."""
    if user.learning_settings is not None:
        return user.learning_settings

    settings = UserLearningSettings(user_id=user.id)
    db.add(settings)
    db.flush()
    user.learning_settings = settings
    return settings


def get_configured_users(db: Session) -> list[VocabuildaryUser]:
    """Return users that have enough Telegram settings for sends."""
    stmt = (
        select(VocabuildaryUser)
        .where(VocabuildaryUser.telegram_bot_token.is_not(None))
        .where(VocabuildaryUser.telegram_chat_id.is_not(None))
        .order_by(VocabuildaryUser.id.asc())
    )
    return list(db.execute(stmt).scalars())


def update_telegram_settings(
    db: Session,
    user: VocabuildaryUser,
    payload: dict[str, Any],
) -> VocabuildaryUser:
    """Update Telegram settings without accidentally exposing saved secrets."""
    if "telegram_bot_token" in payload:
        token = str(payload.get("telegram_bot_token") or "").strip()
        if token:
            user.telegram_bot_token = token

    if payload.get("clear_telegram_bot_token") is True:
        user.telegram_bot_token = None

    if "telegram_chat_id" in payload:
        chat_id = str(payload.get("telegram_chat_id") or "").strip()
        user.telegram_chat_id = chat_id or None

    learning_payload = payload.get("learning")
    if isinstance(learning_payload, dict):
        settings = get_or_create_learning_settings(db, user)
        _update_learning_settings(settings, learning_payload)

    user.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(user)
    return user


def _bounded_int(value: Any, *, minimum: int, maximum: int) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return max(minimum, min(maximum, parsed))


def _normalize_intervals(value: Any) -> list[int] | None:
    if isinstance(value, str):
        raw_values = value.split(",")
    elif isinstance(value, list):
        raw_values = value
    else:
        return None

    intervals: list[int] = []
    for raw_value in raw_values:
        try:
            interval = int(str(raw_value).strip())
        except ValueError:
            continue
        if interval > 0:
            intervals.append(interval)
    return intervals or None


def _update_learning_settings(
    settings: UserLearningSettings,
    payload: dict[str, Any],
) -> None:
    """Apply user-editable learning settings with conservative bounds."""
    if "enabled" in payload:
        settings.enabled = bool(payload.get("enabled"))

    if "target_language_code" in payload:
        target_language_code = str(payload.get("target_language_code") or "").strip().lower()
        if target_language_code:
            settings.target_language_code = target_language_code

    if "daily_review_words" in payload:
        value = _bounded_int(payload.get("daily_review_words"), minimum=0, maximum=12)
        if value is not None:
            settings.daily_review_words = value

    if "daily_cloze_words" in payload:
        value = _bounded_int(payload.get("daily_cloze_words"), minimum=0, maximum=3)
        if value is not None:
            settings.daily_cloze_words = value

    if "mastery_encounters" in payload:
        value = _bounded_int(payload.get("mastery_encounters"), minimum=1, maximum=30)
        if value is not None:
            settings.mastery_encounters = value

    if "review_intervals" in payload:
        intervals = _normalize_intervals(payload.get("review_intervals"))
        if intervals is not None:
            settings.review_intervals = intervals

    settings.updated_at = datetime.now(timezone.utc)


def serialize_learning_settings(settings: UserLearningSettings | None) -> dict[str, Any]:
    """Public learning-settings payload for UI clients."""
    if settings is None:
        return {
            "enabled": True,
            "target_language_code": constants.DEFAULT_TARGET_LANGUAGE_CODE,
            "daily_review_words": constants.DEFAULT_DAILY_REVIEW_WORDS,
            "daily_cloze_words": constants.DEFAULT_DAILY_CLOZE_WORDS,
            "mastery_encounters": constants.DEFAULT_MASTERY_ENCOUNTERS,
            "review_intervals": list(constants.DEFAULT_REVIEW_INTERVAL_DAYS),
        }

    return {
        "enabled": bool(settings.enabled),
        "target_language_code": settings.target_language_code,
        "daily_review_words": settings.daily_review_words,
        "daily_cloze_words": settings.daily_cloze_words,
        "mastery_encounters": settings.mastery_encounters,
        "review_intervals": settings.review_intervals or list(constants.DEFAULT_REVIEW_INTERVAL_DAYS),
    }


def serialize_user(user: VocabuildaryUser) -> dict[str, Any]:
    """Public user payload for UI clients."""
    return {
        "id": user.id,
        "identity_key": user.identity_key,
        "gateway_sub": user.gateway_sub,
        "email": user.email,
        "name": user.name,
        "raw_identity_headers": user.raw_identity_headers or {},
        "telegram": {
            "bot_token_set": bool(user.telegram_bot_token),
            "bot_token_hint": _redact_token(user.telegram_bot_token),
            "chat_id": user.telegram_chat_id or "",
            "configured": bool(user.telegram_bot_token and user.telegram_chat_id),
        },
        "learning": serialize_learning_settings(user.learning_settings),
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "updated_at": user.updated_at.isoformat() if user.updated_at else None,
        "last_seen_at": user.last_seen_at.isoformat() if user.last_seen_at else None,
    }
