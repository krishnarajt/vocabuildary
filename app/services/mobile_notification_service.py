"""Mobile device registration and native-notification queueing."""

from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common import constants
from app.db.models import (
    DailyLearningSession,
    MobileDevice,
    MobileNotification,
    VocabuildaryUser,
    Word,
)

TAG_RE = re.compile(r"<[^>]+>")


class MobileDeviceValidationError(ValueError):
    """Raised when a mobile-device registration payload is invalid."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _clean_text(value: object, *, limit: int = 500) -> str:
    text = str(value or "").strip()
    return text[:limit]


def _plain_text(value: str) -> str:
    text = TAG_RE.sub(" ", value or "")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _normalize_device_id(value: object) -> str:
    device_id = _clean_text(value, limit=120)
    if not device_id:
        raise MobileDeviceValidationError("device_id is required.")
    return device_id


def serialize_mobile_device(device: MobileDevice) -> dict[str, Any]:
    return {
        "id": device.id,
        "device_id": device.device_id,
        "platform": device.platform,
        "display_name": device.display_name or "",
        "push_token_set": bool(device.push_token),
        "timezone": device.timezone or constants.TZ,
        "app_version": device.app_version or "",
        "enabled": bool(device.enabled),
        "created_at": device.created_at.isoformat() if device.created_at else None,
        "updated_at": device.updated_at.isoformat() if device.updated_at else None,
        "last_seen_at": device.last_seen_at.isoformat() if device.last_seen_at else None,
    }


def serialize_mobile_notification(notification: MobileNotification) -> dict[str, Any]:
    return {
        "id": notification.id,
        "device_id": notification.device_id,
        "session_id": notification.session_id,
        "word_id": notification.word_id,
        "kind": notification.notification_kind,
        "title": notification.title,
        "body": notification.body,
        "html_body": notification.html_body or "",
        "metadata": notification.notification_metadata or {},
        "queued_at": notification.queued_at.isoformat() if notification.queued_at else None,
        "delivered_at": notification.delivered_at.isoformat()
        if notification.delivered_at
        else None,
        "opened_at": notification.opened_at.isoformat() if notification.opened_at else None,
    }


def register_mobile_device(
    db: Session,
    user: VocabuildaryUser,
    payload: dict[str, Any],
) -> MobileDevice:
    """Create or update the current mobile app install."""
    device_id = _normalize_device_id(payload.get("device_id"))
    now = _utcnow()
    device = db.execute(
        select(MobileDevice).where(
            MobileDevice.user_id == user.id,
            MobileDevice.device_id == device_id,
        )
    ).scalar_one_or_none()
    if device is None:
        device = MobileDevice(user_id=user.id, device_id=device_id)
        db.add(device)

    device.platform = _clean_text(payload.get("platform") or "android", limit=40) or "android"
    device.display_name = _clean_text(payload.get("display_name"), limit=120) or None
    device.push_token = _clean_text(payload.get("push_token"), limit=2048) or None
    device.timezone = _clean_text(payload.get("timezone") or constants.TZ, limit=80) or constants.TZ
    device.app_version = _clean_text(payload.get("app_version"), limit=80) or None
    device.enabled = bool(payload.get("enabled", True))
    device.last_seen_at = now
    device.updated_at = now

    db.commit()
    db.refresh(device)
    return device


def list_mobile_devices_for_user(db: Session, user: VocabuildaryUser) -> list[MobileDevice]:
    return list(
        db.execute(
            select(MobileDevice)
            .where(MobileDevice.user_id == user.id)
            .order_by(MobileDevice.last_seen_at.desc(), MobileDevice.id.desc())
        ).scalars()
    )


def user_has_enabled_mobile_devices(db: Session, user: VocabuildaryUser) -> bool:
    device_id = db.execute(
        select(MobileDevice.id)
        .where(MobileDevice.user_id == user.id)
        .where(MobileDevice.enabled.is_(True))
        .limit(1)
    ).scalar_one_or_none()
    return device_id is not None


def queue_mobile_notifications_for_user(
    db: Session,
    user: VocabuildaryUser,
    *,
    title: str,
    body: str,
    html_body: str | None = None,
    word: Word | None = None,
    session: DailyLearningSession | None = None,
    kind: str = "daily",
    metadata: dict[str, Any] | None = None,
) -> int:
    """Queue one notification row per enabled device for the user."""
    devices = (
        db.execute(
            select(MobileDevice)
            .where(MobileDevice.user_id == user.id)
            .where(MobileDevice.enabled.is_(True))
            .order_by(MobileDevice.id.asc())
        )
        .scalars()
        .all()
    )
    if not devices:
        return 0

    now = _utcnow()
    plain_body = _plain_text(body)
    if not plain_body and html_body:
        plain_body = _plain_text(html_body)
    if not plain_body:
        plain_body = "Your Vocabuildary reminder is ready."

    for device in devices:
        device.last_seen_at = now
        db.add(
            MobileNotification(
                user_id=user.id,
                device_id=device.id,
                session_id=session.id if session is not None else None,
                word_id=word.id if word is not None else None,
                notification_kind=_clean_text(kind, limit=40) or "daily",
                title=_clean_text(title, limit=140) or "Vocabuildary",
                body=plain_body[:4000],
                html_body=html_body or body,
                notification_metadata=metadata or {},
                queued_at=now,
            )
        )

    db.flush()
    return len(devices)


def get_pending_mobile_notifications(
    db: Session,
    user: VocabuildaryUser,
    *,
    device_id: str | None = None,
    limit: int = 20,
) -> list[MobileNotification]:
    stmt = (
        select(MobileNotification)
        .join(MobileNotification.device)
        .where(MobileNotification.user_id == user.id)
        .where(MobileNotification.delivered_at.is_(None))
        .order_by(MobileNotification.queued_at.asc(), MobileNotification.id.asc())
        .limit(max(1, min(int(limit or 20), 100)))
    )
    if device_id:
        stmt = stmt.where(MobileDevice.device_id == device_id)
    return list(db.execute(stmt).scalars())


def mark_mobile_notification_delivered(
    db: Session,
    user: VocabuildaryUser,
    notification_id: int,
) -> MobileNotification:
    notification = db.execute(
        select(MobileNotification).where(
            MobileNotification.id == notification_id,
            MobileNotification.user_id == user.id,
        )
    ).scalar_one_or_none()
    if notification is None:
        raise LookupError("Mobile notification not found.")
    notification.delivered_at = notification.delivered_at or _utcnow()
    db.commit()
    db.refresh(notification)
    return notification


def mark_mobile_notification_opened(
    db: Session,
    user: VocabuildaryUser,
    notification_id: int,
) -> MobileNotification:
    notification = db.execute(
        select(MobileNotification).where(
            MobileNotification.id == notification_id,
            MobileNotification.user_id == user.id,
        )
    ).scalar_one_or_none()
    if notification is None:
        raise LookupError("Mobile notification not found.")
    now = _utcnow()
    notification.delivered_at = notification.delivered_at or now
    notification.opened_at = notification.opened_at or now
    db.commit()
    db.refresh(notification)
    return notification
