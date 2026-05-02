"""Per-user reminder slot settings and due-slot delivery."""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.common import constants
from app.db.database import get_db_session
from app.db.models import DailyLearningSession, ReminderLog, UserReminderSlot, VocabuildaryUser
from app.services.mobile_notification_service import queue_mobile_notifications_for_user
from app.services.notification_service import create_notifier_for_user
from app.services.word_service import send_daily_word

logger = logging.getLogger(__name__)

TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


class ReminderScheduleValidationError(ValueError):
    """Raised when reminder slot input is invalid."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def normalize_time_of_day(value: Any) -> str:
    text = str(value or "").strip()
    match = TIME_RE.match(text)
    if not match:
        raise ReminderScheduleValidationError("Reminder time must use 24-hour HH:MM format.")
    return f"{match.group(1)}:{match.group(2)}"


def _timezone(value: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(value or constants.TZ)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def _slot_date(slot: UserReminderSlot, now: datetime | None = None) -> date:
    current = now or _utcnow()
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(_timezone(slot.timezone)).date()


def _is_due(slot: UserReminderSlot, now: datetime | None = None) -> bool:
    current = now or _utcnow()
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    local_now = current.astimezone(_timezone(slot.timezone))
    today = local_now.date()
    if slot.last_sent_on == today:
        return False
    hour, minute = [int(part) for part in slot.time_of_day.split(":", 1)]
    return (local_now.hour, local_now.minute) >= (hour, minute)


def serialize_reminder_slot(slot: UserReminderSlot) -> dict[str, Any]:
    return {
        "id": slot.id,
        "label": slot.label or "",
        "time_of_day": slot.time_of_day,
        "timezone": slot.timezone or constants.TZ,
        "enabled": bool(slot.enabled),
        "last_sent_on": slot.last_sent_on.isoformat() if slot.last_sent_on else None,
        "created_at": slot.created_at.isoformat() if slot.created_at else None,
        "updated_at": slot.updated_at.isoformat() if slot.updated_at else None,
    }


def list_reminder_slots_for_user(
    db: Session,
    user: VocabuildaryUser,
    ensure_default: bool = True,
) -> list[UserReminderSlot]:
    stmt = (
        select(UserReminderSlot)
        .where(UserReminderSlot.user_id == user.id)
        .order_by(UserReminderSlot.time_of_day.asc(), UserReminderSlot.id.asc())
    )
    slots = list(db.execute(stmt).scalars())
    if slots or not ensure_default:
        return slots

    slot = UserReminderSlot(
        user_id=user.id,
        label="Morning",
        time_of_day="09:00",
        timezone=constants.TZ,
        enabled=False,
    )
    db.add(slot)
    db.commit()
    db.refresh(slot)
    return [slot]


def update_reminder_slots_for_user(
    db: Session,
    user: VocabuildaryUser,
    payload: dict[str, Any],
) -> list[UserReminderSlot]:
    raw_slots = payload.get("slots")
    if not isinstance(raw_slots, list):
        raise ReminderScheduleValidationError("slots must be a list.")
    if len(raw_slots) > 12:
        raise ReminderScheduleValidationError("Use 12 reminder slots or fewer.")

    existing_slots = {
        slot.id: slot
        for slot in db.execute(
            select(UserReminderSlot).where(UserReminderSlot.user_id == user.id)
        ).scalars()
    }
    keep_ids: set[int] = set()
    seen_times: set[str] = set()
    now = _utcnow()

    for raw_slot in raw_slots:
        if not isinstance(raw_slot, dict):
            continue
        time_of_day = normalize_time_of_day(raw_slot.get("time_of_day"))
        if time_of_day in seen_times:
            raise ReminderScheduleValidationError("Reminder times must be unique.")
        seen_times.add(time_of_day)

        slot_id = raw_slot.get("id")
        slot = None
        try:
            slot_id_int = int(slot_id) if slot_id not in (None, "") else None
        except (TypeError, ValueError):
            slot_id_int = None
        if slot_id_int is not None:
            slot = existing_slots.get(slot_id_int)
            if slot is not None:
                keep_ids.add(slot.id)

        if slot is None:
            slot = UserReminderSlot(user_id=user.id)
            db.add(slot)
            db.flush()
            keep_ids.add(slot.id)

        slot.label = str(raw_slot.get("label") or "").strip() or None
        slot.time_of_day = time_of_day
        slot.timezone = str(raw_slot.get("timezone") or constants.TZ).strip() or constants.TZ
        slot.enabled = bool(raw_slot.get("enabled", True))
        slot.updated_at = now

    for slot_id, slot in existing_slots.items():
        if slot_id not in keep_ids:
            db.delete(slot)

    db.commit()
    return list_reminder_slots_for_user(db, user, ensure_default=False)


def process_due_reminder_slots(db: Optional[Session] = None) -> list[dict[str, Any]]:
    owns_session = db is None
    db = db or get_db_session()
    try:
        slots = (
            db.execute(
                select(UserReminderSlot)
                .options(joinedload(UserReminderSlot.user))
                .where(UserReminderSlot.enabled.is_(True))
                .order_by(UserReminderSlot.time_of_day.asc(), UserReminderSlot.id.asc())
            )
            .unique()
            .scalars()
            .all()
        )
        results = []
        for slot in slots:
            user = slot.user
            if user is None or not user.notifications_configured or not _is_due(slot):
                continue
            results.append(_deliver_slot(db, user, slot))
        return results
    finally:
        if owns_session:
            db.close()


def process_due_reminder_slots_for_user(
    db: Session,
    user: VocabuildaryUser,
) -> list[dict[str, Any]]:
    """Process due reminder slots for a single authenticated user."""
    slots = (
        db.execute(
            select(UserReminderSlot)
            .where(UserReminderSlot.user_id == user.id)
            .where(UserReminderSlot.enabled.is_(True))
            .order_by(UserReminderSlot.time_of_day.asc(), UserReminderSlot.id.asc())
        )
        .scalars()
        .all()
    )
    results = []
    for slot in slots:
        if not user.notifications_configured or not _is_due(slot):
            continue
        results.append(_deliver_slot(db, user, slot))
    return results


def _deliver_slot(
    db: Session,
    user: VocabuildaryUser,
    slot: UserReminderSlot,
) -> dict[str, Any]:
    today = _slot_date(slot)
    session = db.execute(
        select(DailyLearningSession)
        .where(DailyLearningSession.user_id == user.id)
        .where(DailyLearningSession.session_date == today)
        .limit(1)
    ).scalar_one_or_none()

    if session is not None and session.sent_at is not None and session.message_text:
        provider_sent = False
        if user.provider_configured:
            notifier = create_notifier_for_user(user)
            notifier.send_message(session.message_text, parse_mode="HTML")
            provider_sent = True
        mobile_count = queue_mobile_notifications_for_user(
            db,
            user,
            title=f"Vocabuildary: {session.new_word.word if session.new_word else 'Daily word'}",
            body=session.message_text,
            html_body=session.message_text,
            word=session.new_word,
            session=session,
            kind="reminder_slot",
            metadata={"slot_id": slot.id, "slot_label": slot.label or ""},
        )
        if not provider_sent and mobile_count == 0:
            raise RuntimeError("No notification delivery channel is configured.")
        slot.last_sent_on = today
        slot.updated_at = _utcnow()
        db.add(
            ReminderLog(
                user_id=user.id,
                word_id=session.new_word_id,
                word_text=session.new_word.word if session.new_word else "",
            )
        )
        db.commit()
        logger.info("Delivered repeated reminder slot id=%s user_id=%s", slot.id, user.id)
        return {
            "slot_id": slot.id,
            "user_id": user.id,
            "sent": True,
            "repeated": True,
            "mobile_count": mobile_count,
        }

    success, word = send_daily_word(db=db, user=user)
    if success and word is not None:
        slot.last_sent_on = today
        slot.updated_at = _utcnow()
        db.commit()
    return {
        "slot_id": slot.id,
        "user_id": user.id,
        "sent": bool(success and word is not None),
        "repeated": False,
        "word": word.word if word is not None else None,
    }
