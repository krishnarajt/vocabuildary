"""
Word service: business logic for the daily teaching flow.

The original app sent one global random word. The current flow plans a daily
one-sided lesson per user: one new word, a configurable set of reminder words,
one optional fill-in-the-blank, and the previous blank's answer reveal.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Optional, Tuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, joinedload

from app.common import constants
from app.db.database import get_db_session
from app.db.models import (
    Book,
    BookWord,
    DailyLearningSession,
    ReminderLog,
    UserLearningSettings,
    UserWordExposure,
    UserWordProgress,
    VocabuildaryUser,
    Word,
)
from app.services.reminder_content_service import (
    ClozeAnswerReveal,
    build_reminder_message,
    render_reminder_message,
)
from app.services.language_skill_service import (
    get_frequency_band_for_level,
    get_user_language_level,
)
from app.services.notification_service import (
    NotificationSender,
    create_legacy_notifier,
    create_notifier_for_user,
    legacy_notification_configured,
    notification_provider_label,
)
from app.services.mobile_notification_service import queue_mobile_notifications_for_user
from app.services.user_service import (
    get_configured_users,
    get_or_create_learning_settings,
    serialize_learning_settings,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SendResult:
    success: bool
    word: Optional[Word]
    user: Optional[VocabuildaryUser]
    error: Optional[str] = None


@dataclass
class DailyLearningPlan:
    """User-specific plan for one daily message."""

    session: DailyLearningSession
    settings: UserLearningSettings
    new_word: Word
    context_words: list[Word]
    cloze_word: Optional[Word]
    previous_cloze: Optional[ClozeAnswerReveal]
    previous_cloze_session: Optional[DailyLearningSession]


class LearningPlanLockedError(RuntimeError):
    """Raised when a sent daily plan can no longer be edited."""


class LearningPlanValidationError(ValueError):
    """Raised when a requested learning-plan edit is not valid."""


def _learning_today(now: datetime | None = None) -> date:
    """Return today's learning date in the configured app timezone."""
    try:
        tz = ZoneInfo(constants.TZ)
    except ZoneInfoNotFoundError:
        tz = timezone.utc

    current = now or datetime.now(tz)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(tz).date()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _review_intervals(settings: UserLearningSettings) -> list[int]:
    raw_intervals = settings.review_intervals or constants.DEFAULT_REVIEW_INTERVAL_DAYS
    intervals: list[int] = []
    for raw_interval in raw_intervals:
        try:
            interval = int(raw_interval)
        except (TypeError, ValueError):
            continue
        if interval > 0:
            intervals.append(interval)
    return intervals or list(constants.DEFAULT_REVIEW_INTERVAL_DAYS)


def _get_words_by_ids(db: Session, word_ids: list[int]) -> list[Word]:
    if not word_ids:
        return []
    words = db.execute(select(Word).where(Word.id.in_(word_ids))).scalars().all()
    words_by_id = {word.id: word for word in words}
    return [words_by_id[word_id] for word_id in word_ids if word_id in words_by_id]


def _serialize_word_for_plan(word: Word | None) -> dict | None:
    if word is None:
        return None
    return {
        "id": word.id,
        "word": word.word,
        "meaning": word.meaning,
        "example": word.example,
        "language_code": word.language_code,
        "part_of_speech": word.part_of_speech,
        "pronunciation": word.pronunciation,
        "origin_language": word.origin_language,
        "etymology": word.etymology,
        "register": word.register,
        "difficulty_level": word.difficulty_level,
        "frequency_rank": word.frequency_rank,
        "frequency_score": word.frequency_score,
        "zipf_frequency": word.zipf_frequency,
        "frequency_source": word.frequency_source,
        "definition_source": word.definition_source,
    }


def _iso_date(value: date | None) -> str | None:
    return value.isoformat() if value else None


def _iso_datetime(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _get_or_create_progress(
    db: Session,
    user: VocabuildaryUser,
    word: Word,
    study_date: date,
) -> UserWordProgress:
    stmt = select(UserWordProgress).where(
        UserWordProgress.user_id == user.id,
        UserWordProgress.word_id == word.id,
    )
    progress = db.execute(stmt).scalar_one_or_none()
    if progress is not None:
        return progress

    progress = UserWordProgress(
        user_id=user.id,
        word_id=word.id,
        status="learning",
        introduced_on=study_date,
        next_due_on=study_date,
    )
    db.add(progress)
    db.flush()
    return progress


def get_random_unsent_word(db: Session) -> Optional[Word]:
    """
    Legacy fallback: return a random global word where sent=False.

    This keeps the environment-based fallback usable when no signed-in users
    have configured notifications yet.
    """
    unsent = db.query(Word).filter(Word.sent.is_(False)).all()

    if not unsent:
        logger.info("All words sent. Resetting sent flags for the next legacy loop.")
        db.execute(update(Word).values(sent=False))
        db.commit()
        unsent = db.query(Word).filter(Word.sent.is_(False)).all()

    if not unsent:
        logger.warning("No words in the database at all. Nothing to send.")
        return None

    chosen = random.choice(unsent)
    logger.info("Picked legacy word id=%s word=%r", chosen.id, chosen.word)
    return chosen


def mark_word_sent(db: Session, word_id: int) -> None:
    """Stage sent=True for a specific legacy word id."""
    db.execute(update(Word).where(Word.id == word_id).values(sent=True))
    logger.debug("Marked word id=%s as sent.", word_id)


def log_reminder(
    db: Session,
    word: Word,
    user: Optional[VocabuildaryUser] = None,
) -> None:
    """Stage reminder history after a successful real send."""
    db.add(ReminderLog(word_id=word.id, word_text=word.word, user_id=user.id if user else None))
    logger.debug("Logged reminder for word id=%s.", word.id)


def get_recent_reminders(
    limit: int = 5,
    days: int | None = None,
    db: Optional[Session] = None,
    user: Optional[VocabuildaryUser] = None,
    user_id: Optional[int] = None,
) -> list[ReminderLog]:
    """Return recent reminder history, newest first."""
    owns_session = db is None
    db = db or get_db_session()

    try:
        filter_user_id = user.id if user is not None else user_id
        stmt = select(ReminderLog).options(joinedload(ReminderLog.word))
        if filter_user_id is not None:
            stmt = stmt.where(ReminderLog.user_id == filter_user_id)
        if days is not None:
            days = max(1, min(int(days), 3650))
            stmt = stmt.where(ReminderLog.reminded_at >= _utc_now() - timedelta(days=days))
        stmt = stmt.order_by(ReminderLog.reminded_at.desc(), ReminderLog.id.desc()).limit(limit)
        return list(db.execute(stmt).scalars())
    finally:
        if owns_session:
            db.close()


def _select_new_word(
    db: Session,
    user: VocabuildaryUser,
    settings: UserLearningSettings,
) -> Optional[Word]:
    seen_word_ids = select(UserWordProgress.word_id).where(UserWordProgress.user_id == user.id)
    user_level = get_user_language_level(db, user, settings.target_language_code)
    frequency_band = get_frequency_band_for_level(
        db,
        settings.target_language_code,
        user_level.level_code if user_level is not None else None,
    )

    def apply_frequency_band(stmt):
        if frequency_band is None:
            return stmt
        if frequency_band.min_frequency_rank is not None:
            stmt = stmt.where(Word.frequency_rank.is_not(None))
            stmt = stmt.where(Word.frequency_rank >= frequency_band.min_frequency_rank)
        if frequency_band.max_frequency_rank is not None:
            stmt = stmt.where(Word.frequency_rank.is_not(None))
            stmt = stmt.where(Word.frequency_rank <= frequency_band.max_frequency_rank)
        return stmt

    book_word_base_stmt = (
        select(Word)
        .join(BookWord, BookWord.word_id == Word.id)
        .join(Book, Book.id == BookWord.book_id)
        .where(Book.user_id == user.id)
        .where(Book.learning_enabled.is_(True))
        .where(BookWord.language_code == settings.target_language_code)
        .where(Word.id.not_in(seen_word_ids))
        .order_by(
            BookWord.rank_in_book.asc().nullslast(),
            Word.frequency_rank.asc().nullslast(),
            Word.word.asc(),
        )
    )
    book_word = None
    if frequency_band is not None:
        book_word = db.execute(
            apply_frequency_band(book_word_base_stmt).limit(1)
        ).scalar_one_or_none()
    if book_word is None:
        book_word = db.execute(book_word_base_stmt.limit(1)).scalar_one_or_none()
    if book_word is not None:
        return book_word

    base_stmt = (
        select(Word)
        .where(Word.language_code == settings.target_language_code)
        .where(Word.id.not_in(seen_word_ids))
        .order_by(Word.frequency_rank.asc().nullslast(), func.random())
    )
    word = None
    if frequency_band is not None:
        word = db.execute(apply_frequency_band(base_stmt).limit(1)).scalar_one_or_none()
    if word is None:
        word = db.execute(base_stmt.limit(1)).scalar_one_or_none()
    if word is not None:
        return word

    # If the user has already touched every word in the target language, keep
    # the ritual alive by revisiting the least-progressed word as the primary.
    progress_stmt = (
        select(UserWordProgress)
        .join(UserWordProgress.word)
        .options(joinedload(UserWordProgress.word))
        .where(UserWordProgress.user_id == user.id)
        .where(Word.language_code == settings.target_language_code)
        .order_by(
            UserWordProgress.progress_percent.asc(),
            UserWordProgress.last_seen_on.asc().nullsfirst(),
            UserWordProgress.id.asc(),
        )
        .limit(1)
    )
    progress = db.execute(progress_stmt).unique().scalar_one_or_none()
    return progress.word if progress is not None else None


def _progress_review_query(
    user: VocabuildaryUser,
    settings: UserLearningSettings,
    excluded_word_ids: set[int],
):
    stmt = (
        select(UserWordProgress)
        .join(UserWordProgress.word)
        .options(joinedload(UserWordProgress.word))
        .where(UserWordProgress.user_id == user.id)
        .where(UserWordProgress.status != "reset")
        .where(Word.language_code == settings.target_language_code)
    )
    if excluded_word_ids:
        stmt = stmt.where(UserWordProgress.word_id.not_in(excluded_word_ids))
    return stmt


def _select_review_progress(
    db: Session,
    user: VocabuildaryUser,
    settings: UserLearningSettings,
    study_date: date,
    excluded_word_ids: set[int],
) -> list[UserWordProgress]:
    quota = max(0, int(settings.daily_review_words or 0))
    if quota == 0:
        return []

    due_stmt = (
        _progress_review_query(user, settings, excluded_word_ids)
        .where(UserWordProgress.next_due_on.is_not(None))
        .where(UserWordProgress.next_due_on <= study_date)
        .order_by(
            UserWordProgress.next_due_on.asc(),
            UserWordProgress.progress_percent.asc(),
            UserWordProgress.id.asc(),
        )
        .limit(quota)
    )
    selected = list(db.execute(due_stmt).unique().scalars())
    if len(selected) >= quota:
        return selected

    selected_ids = {progress.word_id for progress in selected}
    fill_excluded_ids = excluded_word_ids | selected_ids
    fill_stmt = (
        _progress_review_query(user, settings, fill_excluded_ids)
        .where(UserWordProgress.last_seen_on.is_not(None))
        .where(UserWordProgress.last_seen_on < study_date)
        .order_by(
            UserWordProgress.progress_percent.asc(),
            UserWordProgress.last_seen_on.asc(),
            UserWordProgress.id.asc(),
        )
        .limit(quota - len(selected))
    )
    selected.extend(db.execute(fill_stmt).unique().scalars())
    return selected


def _get_previous_cloze_session(
    db: Session,
    user: VocabuildaryUser,
    study_date: date,
) -> Optional[DailyLearningSession]:
    stmt = (
        select(DailyLearningSession)
        .options(joinedload(DailyLearningSession.cloze_word))
        .where(DailyLearningSession.user_id == user.id)
        .where(DailyLearningSession.session_date < study_date)
        .where(DailyLearningSession.cloze_word_id.is_not(None))
        .where(DailyLearningSession.cloze_prompt.is_not(None))
        .where(DailyLearningSession.sent_at.is_not(None))
        .where(DailyLearningSession.cloze_answer_revealed_at.is_(None))
        .order_by(DailyLearningSession.session_date.desc(), DailyLearningSession.id.desc())
        .limit(1)
    )
    return db.execute(stmt).unique().scalar_one_or_none()


def _cloze_reveal_from_session(
    session: DailyLearningSession | None,
) -> Optional[ClozeAnswerReveal]:
    if session is None or session.cloze_word is None:
        return None
    return ClozeAnswerReveal(
        word=session.cloze_word.word,
        meaning=session.cloze_word.meaning,
        prompt=session.cloze_prompt or "",
        answer=session.cloze_answer or session.cloze_word.word,
    )


def _hydrate_existing_plan(
    db: Session,
    session: DailyLearningSession,
    settings: UserLearningSettings,
) -> DailyLearningPlan:
    context_word_ids = [int(word_id) for word_id in session.context_word_ids or []]
    previous_session = (
        db.get(DailyLearningSession, session.previous_cloze_session_id)
        if session.previous_cloze_session_id
        else None
    )

    return DailyLearningPlan(
        session=session,
        settings=settings,
        new_word=session.new_word or db.get(Word, session.new_word_id),
        context_words=_get_words_by_ids(db, context_word_ids),
        cloze_word=session.cloze_word or (
            db.get(Word, session.cloze_word_id) if session.cloze_word_id else None
        ),
        previous_cloze=_cloze_reveal_from_session(previous_session),
        previous_cloze_session=previous_session,
    )


def build_daily_learning_plan(
    db: Session,
    user: VocabuildaryUser,
    study_date: date | None = None,
) -> Optional[DailyLearningPlan]:
    """
    Create or return today's user-specific learning plan.

    The function stages DB rows but does not commit; the caller commits only
    after the notification provider accepts the message.
    """
    settings = get_or_create_learning_settings(db, user)
    if not settings.enabled:
        logger.info("Learning disabled for user id=%s", user.id)
        return None

    study_date = study_date or _learning_today()
    existing_stmt = (
        select(DailyLearningSession)
        .options(
            joinedload(DailyLearningSession.new_word),
            joinedload(DailyLearningSession.cloze_word),
        )
        .where(DailyLearningSession.user_id == user.id)
        .where(DailyLearningSession.session_date == study_date)
        .limit(1)
    )
    existing = db.execute(existing_stmt).unique().scalar_one_or_none()
    if existing is not None:
        return _hydrate_existing_plan(db, existing, settings)

    new_word = _select_new_word(db, user, settings)
    if new_word is None:
        logger.warning("No words available for user id=%s", user.id)
        return None

    _get_or_create_progress(db, user, new_word, study_date)
    previous_session = _get_previous_cloze_session(db, user, study_date)
    previous_cloze = _cloze_reveal_from_session(previous_session)

    excluded_word_ids = {new_word.id}
    if previous_session is not None and previous_session.cloze_word_id is not None:
        excluded_word_ids.add(previous_session.cloze_word_id)

    review_progress = _select_review_progress(
        db,
        user,
        settings,
        study_date,
        excluded_word_ids,
    )
    review_words = [progress.word for progress in review_progress]
    cloze_word = review_words[0] if settings.daily_cloze_words and review_words else None
    context_words = review_words[1:] if cloze_word is not None else review_words

    session = DailyLearningSession(
        user_id=user.id,
        session_date=study_date,
        new_word_id=new_word.id,
        cloze_word_id=cloze_word.id if cloze_word is not None else None,
        previous_cloze_session_id=previous_session.id if previous_session is not None else None,
        previous_cloze_word_id=previous_session.cloze_word_id
        if previous_session is not None
        else None,
        reminder_word_ids=[word.id for word in review_words],
        context_word_ids=[word.id for word in context_words],
        cloze_answer=cloze_word.word if cloze_word is not None else None,
    )
    db.add(session)
    db.flush()

    return DailyLearningPlan(
        session=session,
        settings=settings,
        new_word=new_word,
        context_words=context_words,
        cloze_word=cloze_word,
        previous_cloze=previous_cloze,
        previous_cloze_session=previous_session,
    )


def serialize_daily_learning_plan(plan: DailyLearningPlan) -> dict:
    """Public daily-plan payload for UI clients."""
    review_words: list[Word] = []
    if plan.cloze_word is not None:
        review_words.append(plan.cloze_word)
    review_words.extend(
        word for word in plan.context_words if plan.cloze_word is None or word.id != plan.cloze_word.id
    )

    previous_cloze = None
    if plan.previous_cloze is not None:
        previous_cloze = {
            "word": plan.previous_cloze.word,
            "meaning": plan.previous_cloze.meaning,
            "prompt": plan.previous_cloze.prompt,
            "answer": plan.previous_cloze.answer,
            "session_id": plan.previous_cloze_session.id
            if plan.previous_cloze_session is not None
            else None,
            "session_date": _iso_date(plan.previous_cloze_session.session_date)
            if plan.previous_cloze_session is not None
            else None,
        }

    session = plan.session
    return {
        "session": {
            "id": session.id,
            "date": _iso_date(session.session_date),
            "sent_at": _iso_datetime(session.sent_at),
            "created_at": _iso_datetime(session.created_at),
            "updated_at": _iso_datetime(session.updated_at),
            "cloze_answer_revealed_at": _iso_datetime(session.cloze_answer_revealed_at),
        },
        "new_word": _serialize_word_for_plan(plan.new_word),
        "cloze_word": _serialize_word_for_plan(plan.cloze_word),
        "context_words": [_serialize_word_for_plan(word) for word in plan.context_words],
        "review_words": [_serialize_word_for_plan(word) for word in review_words],
        "previous_cloze": previous_cloze,
        "generated_content": session.generated_content or {},
        "message_text": session.message_text,
        "cloze_prompt": session.cloze_prompt,
        "cloze_answer": session.cloze_answer,
        "settings": serialize_learning_settings(plan.settings),
    }


def get_daily_learning_plan_preview(
    db: Session,
    user: VocabuildaryUser,
    study_date: date | None = None,
) -> Optional[DailyLearningPlan]:
    """Create or return today's plan and persist the preview session."""
    study_date = study_date or _learning_today()
    plan = build_daily_learning_plan(db, user, study_date=study_date)
    if plan is None:
        db.rollback()
        return None

    db.commit()
    return build_daily_learning_plan(db, user, study_date=study_date)


def _drop_unsent_preview_progress(
    db: Session,
    user: VocabuildaryUser,
    session: DailyLearningSession,
) -> None:
    progress = db.execute(
        select(UserWordProgress).where(
            UserWordProgress.user_id == user.id,
            UserWordProgress.word_id == session.new_word_id,
        )
    ).scalar_one_or_none()
    if progress is None:
        return

    exposure_id = db.execute(
        select(UserWordExposure.id)
        .where(UserWordExposure.progress_id == progress.id)
        .limit(1)
    ).scalar_one_or_none()
    if exposure_id is not None:
        return

    if (
        progress.encounter_count == 0
        and progress.introduced_on == session.session_date
        and progress.first_seen_at is None
    ):
        db.delete(progress)


def rebuild_daily_learning_plan(
    db: Session,
    user: VocabuildaryUser,
    study_date: date | None = None,
) -> Optional[DailyLearningPlan]:
    """Discard today's unsent plan and choose a fresh one."""
    study_date = study_date or _learning_today()
    existing = db.execute(
        select(DailyLearningSession)
        .where(DailyLearningSession.user_id == user.id)
        .where(DailyLearningSession.session_date == study_date)
        .limit(1)
    ).scalar_one_or_none()

    if existing is not None:
        if existing.sent_at is not None:
            raise LearningPlanLockedError("Today's plan has already been sent.")
        _drop_unsent_preview_progress(db, user, existing)
        db.delete(existing)
        db.flush()

    plan = build_daily_learning_plan(db, user, study_date=study_date)
    if plan is None:
        db.rollback()
        return None

    db.commit()
    return build_daily_learning_plan(db, user, study_date=study_date)


def _parse_optional_word_id(value: object) -> int | None:
    if value in (None, "", False):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise LearningPlanValidationError("Word id must be a number.") from exc
    return parsed if parsed > 0 else None


def _parse_word_id_list(value: object) -> list[int]:
    if not isinstance(value, list):
        raise LearningPlanValidationError("Context word ids must be a list.")

    word_ids: list[int] = []
    for raw_word_id in value:
        word_id = _parse_optional_word_id(raw_word_id)
        if word_id is not None and word_id not in word_ids:
            word_ids.append(word_id)
    return word_ids[:12]


def _load_editable_review_words(
    db: Session,
    user: VocabuildaryUser,
    settings: UserLearningSettings,
    word_ids: list[int],
    excluded_word_ids: set[int],
) -> list[Word]:
    if not word_ids:
        return []

    progress_rows = (
        db.execute(
            select(UserWordProgress)
            .join(UserWordProgress.word)
            .options(joinedload(UserWordProgress.word))
            .where(UserWordProgress.user_id == user.id)
            .where(UserWordProgress.word_id.in_(word_ids))
            .where(UserWordProgress.word_id.not_in(excluded_word_ids))
            .where(UserWordProgress.status != "reset")
            .where(UserWordProgress.encounter_count > 0)
            .where(Word.language_code == settings.target_language_code)
        )
        .unique()
        .scalars()
        .all()
    )
    words_by_id = {progress.word_id: progress.word for progress in progress_rows}
    missing_word_ids = [word_id for word_id in word_ids if word_id not in words_by_id]
    if missing_word_ids:
        raise LearningPlanValidationError(
            "Plan reminders must be words this user has already encountered."
        )
    return [words_by_id[word_id] for word_id in word_ids]


def update_daily_learning_plan(
    db: Session,
    user: VocabuildaryUser,
    payload: dict,
    study_date: date | None = None,
) -> Optional[DailyLearningPlan]:
    """Edit today's unsent cloze/context reminder slots."""
    study_date = study_date or _learning_today()
    plan = build_daily_learning_plan(db, user, study_date=study_date)
    if plan is None:
        db.rollback()
        return None
    if plan.session.sent_at is not None:
        db.rollback()
        raise LearningPlanLockedError("Today's plan has already been sent.")

    excluded_word_ids = {plan.new_word.id}
    cloze_word = plan.cloze_word
    context_words = list(plan.context_words)

    if "cloze_word_id" in payload:
        cloze_word_id = _parse_optional_word_id(payload.get("cloze_word_id"))
        cloze_words = _load_editable_review_words(
            db,
            user,
            plan.settings,
            [cloze_word_id] if cloze_word_id is not None else [],
            excluded_word_ids,
        )
        cloze_word = cloze_words[0] if cloze_words else None

    if cloze_word is not None:
        excluded_word_ids.add(cloze_word.id)

    if "context_word_ids" in payload:
        context_word_ids = _parse_word_id_list(payload.get("context_word_ids"))
        context_words = _load_editable_review_words(
            db,
            user,
            plan.settings,
            context_word_ids,
            excluded_word_ids,
        )

    session = plan.session
    session.cloze_word_id = cloze_word.id if cloze_word is not None else None
    session.cloze_answer = cloze_word.word if cloze_word is not None else None
    session.context_word_ids = [word.id for word in context_words]
    session.reminder_word_ids = [
        *([cloze_word.id] if cloze_word is not None else []),
        *[word.id for word in context_words],
    ]
    session.updated_at = _utc_now()
    db.commit()
    return build_daily_learning_plan(db, user, study_date=study_date)


def _apply_progress_exposure(
    db: Session,
    user: VocabuildaryUser,
    word: Word,
    session: DailyLearningSession,
    exposure_kind: str,
    study_date: date,
    now: datetime,
    settings: UserLearningSettings,
) -> None:
    progress = _get_or_create_progress(db, user, word, study_date)
    if progress.first_seen_at is None:
        progress.first_seen_at = now
    if progress.introduced_on is None:
        progress.introduced_on = study_date

    progress.status = "learning"
    progress.last_seen_on = study_date
    progress.last_seen_at = now
    progress.encounter_count = (progress.encounter_count or 0) + 1
    if exposure_kind == "context_example":
        progress.context_encounter_count = (progress.context_encounter_count or 0) + 1
    elif exposure_kind == "cloze_prompt":
        progress.cloze_prompt_count = (progress.cloze_prompt_count or 0) + 1
    elif exposure_kind == "cloze_answer":
        progress.cloze_answer_count = (progress.cloze_answer_count or 0) + 1

    intervals = _review_intervals(settings)
    interval_index = min(max(progress.encounter_count - 1, 0), len(intervals) - 1)
    progress.interval_days = intervals[interval_index]
    progress.schedule_step = min(progress.encounter_count, len(intervals))
    progress.next_due_on = study_date + timedelta(days=progress.interval_days)

    mastery_encounters = max(1, int(settings.mastery_encounters or 1))
    progress.progress_percent = min(
        100,
        round((progress.encounter_count / mastery_encounters) * 100),
    )
    if progress.progress_percent >= 100 and progress.mastered_at is None:
        progress.mastered_at = now

    progress.updated_at = now
    db.add(
        UserWordExposure(
            user_id=user.id,
            word_id=word.id,
            progress_id=progress.id,
            session_id=session.id,
            exposure_date=study_date,
            exposure_kind=exposure_kind,
        )
    )


def _stage_sent_plan(
    db: Session,
    user: VocabuildaryUser,
    plan: DailyLearningPlan,
    message_text: str,
    content_payload: dict,
) -> None:
    now = _utc_now()
    session = plan.session
    session.generated_content = content_payload
    session.message_text = message_text
    session.cloze_prompt = content_payload.get("cloze_prompt") or None
    session.cloze_answer = plan.cloze_word.word if plan.cloze_word is not None else None
    session.sent_at = now
    session.updated_at = now

    _apply_progress_exposure(
        db,
        user,
        plan.new_word,
        session,
        "new_word",
        session.session_date,
        now,
        plan.settings,
    )
    for context_word in plan.context_words:
        _apply_progress_exposure(
            db,
            user,
            context_word,
            session,
            "context_example",
            session.session_date,
            now,
            plan.settings,
        )
    if plan.cloze_word is not None:
        _apply_progress_exposure(
            db,
            user,
            plan.cloze_word,
            session,
            "cloze_prompt",
            session.session_date,
            now,
            plan.settings,
        )
    if plan.previous_cloze_session is not None and plan.previous_cloze_session.cloze_word:
        _apply_progress_exposure(
            db,
            user,
            plan.previous_cloze_session.cloze_word,
            session,
            "cloze_answer",
            session.session_date,
            now,
            plan.settings,
        )
        plan.previous_cloze_session.cloze_answer_revealed_at = now
        plan.previous_cloze_session.updated_at = now


def get_word_progress_for_user(
    db: Session,
    user: VocabuildaryUser,
    limit: int = 100,
) -> list[UserWordProgress]:
    """Return progress rows for UI display, least-mastered first."""
    stmt = (
        select(UserWordProgress)
        .options(joinedload(UserWordProgress.word))
        .where(UserWordProgress.user_id == user.id)
        .order_by(
            UserWordProgress.progress_percent.asc(),
            UserWordProgress.next_due_on.asc().nullslast(),
            UserWordProgress.id.asc(),
        )
        .limit(max(1, min(limit, 500)))
    )
    return list(db.execute(stmt).unique().scalars())


def get_learnt_words_for_user(
    db: Session,
    user: VocabuildaryUser,
    limit: int = 200,
    offset: int = 0,
) -> list[UserWordProgress]:
    """Return words the user has actually encountered, newest first."""
    stmt = (
        select(UserWordProgress)
        .options(joinedload(UserWordProgress.word))
        .where(UserWordProgress.user_id == user.id)
        .where(UserWordProgress.status != "reset")
        .where(UserWordProgress.encounter_count > 0)
        .order_by(
            UserWordProgress.last_seen_at.desc().nullslast(),
            UserWordProgress.progress_percent.desc(),
            UserWordProgress.id.desc(),
        )
        .offset(max(0, int(offset or 0)))
        .limit(max(1, min(limit, 500)))
    )
    return list(db.execute(stmt).unique().scalars())


def serialize_word_progress(progress: UserWordProgress) -> dict:
    """Public progress payload for UI clients."""
    word = progress.word
    return {
        "word_id": progress.word_id,
        "word": word.word if word else "",
        "meaning": word.meaning if word else "",
        "language_code": word.language_code if word else "",
        "frequency_rank": word.frequency_rank if word else None,
        "zipf_frequency": word.zipf_frequency if word else None,
        "frequency_source": word.frequency_source if word else None,
        "status": progress.status,
        "progress_percent": progress.progress_percent,
        "encounter_count": progress.encounter_count,
        "context_encounter_count": progress.context_encounter_count,
        "cloze_prompt_count": progress.cloze_prompt_count,
        "cloze_answer_count": progress.cloze_answer_count,
        "next_due_on": progress.next_due_on.isoformat() if progress.next_due_on else None,
        "last_seen_on": progress.last_seen_on.isoformat() if progress.last_seen_on else None,
        "introduced_on": progress.introduced_on.isoformat() if progress.introduced_on else None,
        "mastered_at": progress.mastered_at.isoformat() if progress.mastered_at else None,
        "reset_count": progress.reset_count,
    }


def reset_word_progress(
    db: Session,
    user: VocabuildaryUser,
    word_id: int,
) -> UserWordProgress:
    """Reset one learned word back to 0% without deleting historical exposures."""
    stmt = select(UserWordProgress).where(
        UserWordProgress.user_id == user.id,
        UserWordProgress.word_id == word_id,
    )
    progress = db.execute(stmt).scalar_one_or_none()
    if progress is None:
        word = db.get(Word, word_id)
        if word is None:
            raise LookupError("Word progress not found.")
        progress = UserWordProgress(user_id=user.id, word_id=word.id)
        db.add(progress)

    today = _learning_today()
    progress.status = "learning"
    progress.introduced_on = None
    progress.first_seen_at = None
    progress.last_seen_on = None
    progress.last_seen_at = None
    progress.next_due_on = today
    progress.encounter_count = 0
    progress.context_encounter_count = 0
    progress.cloze_prompt_count = 0
    progress.cloze_answer_count = 0
    progress.schedule_step = 0
    progress.interval_days = 0
    progress.progress_percent = 0
    progress.mastered_at = None
    progress.reset_count = (progress.reset_count or 0) + 1
    progress.updated_at = _utc_now()
    db.commit()
    db.refresh(progress)
    return progress


def _send_legacy_daily_word(
    db: Session,
    notifier: NotificationSender,
) -> Tuple[bool, Optional[Word]]:
    word = get_random_unsent_word(db)
    if word is None:
        return False, None

    message = build_reminder_message(word)
    notifier.send_message(message, parse_mode="HTML")
    logger.info("Sent legacy word notification: %r", word.word)

    mark_word_sent(db, word.id)
    log_reminder(db, word, user=None)
    db.commit()
    return True, word


def _send_user_notification(
    db: Session,
    user: VocabuildaryUser,
    *,
    message_text: str,
    word: Word,
    session: DailyLearningSession | None,
    kind: str,
) -> tuple[bool, int]:
    """Deliver to the configured external provider and queue mobile notifications."""
    provider_sent = False
    if user.provider_configured:
        notifier = create_notifier_for_user(user)
        notifier.send_message(message_text, parse_mode="HTML")
        provider_sent = True

    mobile_count = queue_mobile_notifications_for_user(
        db,
        user,
        title=f"Vocabuildary: {word.word}",
        body=message_text,
        html_body=message_text,
        word=word,
        session=session,
        kind=kind,
    )
    if not provider_sent and mobile_count == 0:
        raise RuntimeError("No notification delivery channel is configured.")
    return provider_sent, mobile_count


def send_daily_word(
    db: Optional[Session] = None,
    telegram: Optional[NotificationSender] = None,
    user: Optional[VocabuildaryUser] = None,
) -> Tuple[bool, Optional[Word]]:
    """
    Full daily flow: plan, render, send, and then persist progress.

    With ``user=None`` this falls back to the old global random-word behavior
    for legacy environment-based notification settings.
    """
    owns_session = db is None
    db = db or get_db_session()

    try:
        if user is None:
            notifier = telegram or create_legacy_notifier()
            return _send_legacy_daily_word(db, notifier)

        plan = build_daily_learning_plan(db, user)
        if plan is None:
            db.rollback()
            return False, None
        if plan.session.sent_at is not None:
            logger.info(
                "Daily learning session already sent for user id=%s date=%s",
                user.id,
                plan.session.session_date,
            )
            db.rollback()
            return True, plan.new_word

        rendered = render_reminder_message(
            plan.new_word,
            context_words=plan.context_words,
            cloze_word=plan.cloze_word,
            previous_cloze=plan.previous_cloze,
        )
        provider_sent, mobile_count = _send_user_notification(
            db,
            user,
            message_text=rendered.message,
            word=plan.new_word,
            session=plan.session,
            kind="daily",
        )
        logger.info(
            "Sent daily learning session to user id=%s provider=%s mobile=%s word=%r",
            user.id,
            notification_provider_label(user.notification_provider) if provider_sent else "none",
            mobile_count,
            plan.new_word.word,
        )

        _stage_sent_plan(
            db,
            user,
            plan,
            rendered.message,
            {
                "paragraph": rendered.content.paragraph,
                "history": rendered.content.history,
                "etymology": rendered.content.etymology,
                "cloze_prompt": rendered.content.cloze_prompt,
            },
        )
        log_reminder(db, plan.new_word, user=user)
        db.commit()
        return True, plan.new_word
    except Exception:
        db.rollback()
        raise
    finally:
        if owns_session:
            db.close()


def send_test_notification(
    db: Optional[Session] = None,
    telegram: Optional[NotificationSender] = None,
    user: Optional[VocabuildaryUser] = None,
) -> Tuple[bool, Optional[Word]]:
    """
    Send the same style of reminder as a real send, but without mutating state.
    """
    owns_session = db is None
    db = db or get_db_session()

    try:
        if user is None:
            notifier = telegram or create_legacy_notifier()
            word = get_random_unsent_word(db)
            if word is None:
                return False, None
            message = build_reminder_message(word)
            notifier.send_message(message, parse_mode="HTML")
            db.rollback()
            return True, word

        plan = build_daily_learning_plan(db, user)
        if plan is None:
            db.rollback()
            return False, None

        rendered = render_reminder_message(
            plan.new_word,
            context_words=plan.context_words,
            cloze_word=plan.cloze_word,
            previous_cloze=plan.previous_cloze,
        )
        if user.provider_configured:
            notifier = telegram or create_notifier_for_user(user)
            notifier.send_message(rendered.message, parse_mode="HTML")
        else:
            word = plan.new_word
            db.rollback()
            queue_mobile_notifications_for_user(
                db,
                user,
                title=f"Vocabuildary test: {word.word}",
                body=rendered.message,
                html_body=rendered.message,
                word=word,
                session=None,
                kind="test",
            )
            db.commit()
        logger.info("Sent test notification for %r without mutating state", plan.new_word.word)
        if user.provider_configured:
            db.rollback()
        return True, plan.new_word
    finally:
        if owns_session:
            db.close()


def send_daily_words_to_configured_users(db: Optional[Session] = None) -> list[SendResult]:
    """
    Send one daily learning message to every user with saved notification settings.

    If no users have settings yet, fall back to the legacy env-based
    configuration during the rollout window.
    """
    owns_session = db is None
    db = db or get_db_session()

    try:
        users = get_configured_users(db)
        if not users:
            if not legacy_notification_configured():
                logger.warning("No users have notification settings configured.")
                return []

            success, word = send_daily_word(db=db, telegram=create_legacy_notifier())
            return [SendResult(success=success, word=word, user=None)]

        results: list[SendResult] = []
        for user in users:
            try:
                success, word = send_daily_word(db=db, user=user)
                results.append(SendResult(success=success, word=word, user=user))
            except Exception as exc:
                logger.error(
                    "Failed to send daily learning session to user id=%s email=%r: %s",
                    user.id,
                    user.email,
                    exc,
                    exc_info=True,
                )
                results.append(
                    SendResult(success=False, word=None, user=user, error=str(exc))
                )

        return results
    finally:
        if owns_session:
            db.close()
