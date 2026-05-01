"""
Word service: business logic for the daily-word flow.

Keeps the loop-until-all-seen behaviour: pick a random word with sent=False;
if every row is sent=True, reset them all and pick again.
"""

import logging
import random
from typing import Optional, Tuple

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.adapters.telegram import TelegramAdapter
from app.db.database import get_db_session
from app.db.models import ReminderLog, Word
from app.services.reminder_content_service import build_reminder_message

logger = logging.getLogger(__name__)


def get_random_unsent_word(db: Session) -> Optional[Word]:
    """
    Return a random word where sent=False. If none remain, reset all rows to
    sent=False and try once more. Returns None only if the words table is empty.
    """
    unsent = db.query(Word).filter(Word.sent.is_(False)).all()

    if not unsent:
        logger.info("All words sent. Resetting sent flags for the next loop.")
        db.execute(update(Word).values(sent=False))
        db.commit()
        unsent = db.query(Word).filter(Word.sent.is_(False)).all()

    if not unsent:
        logger.warning("No words in the database at all. Nothing to send.")
        return None

    chosen = random.choice(unsent)
    logger.info("Picked word id=%s word=%r", chosen.id, chosen.word)
    return chosen


def mark_word_sent(db: Session, word_id: int) -> None:
    """Stage sent=True for a specific word id."""
    db.execute(update(Word).where(Word.id == word_id).values(sent=True))
    logger.debug("Marked word id=%s as sent.", word_id)


def log_reminder(db: Session, word: Word) -> None:
    """Stage reminder history after a successful real send."""
    db.add(ReminderLog(word_id=word.id, word_text=word.word))
    logger.debug("Logged reminder for word id=%s.", word.id)


def get_recent_reminders(limit: int = 5, db: Optional[Session] = None) -> list[ReminderLog]:
    """Return recent reminder history, newest first."""
    owns_session = db is None
    db = db or get_db_session()

    try:
        stmt = (
            select(ReminderLog)
            .order_by(ReminderLog.reminded_at.desc(), ReminderLog.id.desc())
            .limit(limit)
        )
        return list(db.execute(stmt).scalars())
    finally:
        if owns_session:
            db.close()


def send_daily_word(
    db: Optional[Session] = None,
    telegram: Optional[TelegramAdapter] = None,
) -> Tuple[bool, Optional[Word]]:
    """
    Full daily flow: pick a word, render the LLM-backed reminder, send it to
    Telegram, then mark it sent.
    """
    owns_session = db is None
    db = db or get_db_session()
    telegram = telegram or TelegramAdapter()

    try:
        word = get_random_unsent_word(db)
        if word is None:
            return False, None

        message = build_reminder_message(word)
        telegram.send_message(message, parse_mode="HTML")
        logger.info("Sent word to Telegram: %r", word.word)

        mark_word_sent(db, word.id)
        log_reminder(db, word)
        db.commit()
        return True, word
    finally:
        if owns_session:
            db.close()


def send_test_notification(
    db: Optional[Session] = None,
    telegram: Optional[TelegramAdapter] = None,
) -> Tuple[bool, Optional[Word]]:
    """
    Send the same style of reminder as a real send, but without mutating state.
    """
    owns_session = db is None
    db = db or get_db_session()
    telegram = telegram or TelegramAdapter()

    try:
        word = get_random_unsent_word(db)
        if word is None:
            return False, None

        message = build_reminder_message(word)
        telegram.send_message(message, parse_mode="HTML")
        logger.info("Sent test notification for word %r without mutating state", word.word)
        return True, word
    finally:
        if owns_session:
            db.close()
