"""
Word service — business logic for the daily-word flow.

Ported from v1 main.py but on SQLAlchemy + Postgres, and decoupled from
the transport (Telegram) via the adapter. Keeps the v1 loop-until-all-
seen behaviour exactly: pick a random word with sent=False; if every
row is sent=True, reset them all and pick again.
"""

import logging
import random
from typing import Optional, Tuple

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.adapters.telegram import TelegramAdapter
from app.db.database import get_db_session
from app.db.models import Word

logger = logging.getLogger(__name__)


def get_random_unsent_word(db: Session) -> Optional[Word]:
    """
    Return a random word where sent=False. If none remain, reset all
    rows to sent=False (loop the list) and try once more. Returns None
    only if the words table is literally empty.
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
    logger.info(f"Picked word id={chosen.id} word={chosen.word!r}")
    return chosen


def mark_word_sent(db: Session, word_id: int) -> None:
    """Flip sent=True for a specific word id."""
    db.execute(update(Word).where(Word.id == word_id).values(sent=True))
    db.commit()
    logger.debug(f"Marked word id={word_id} as sent.")


def format_message(word: Word) -> str:
    """Format the Telegram markdown payload. Same shape as v1."""
    return (
        f"📖 *Word of the Day*\n\n"
        f"*{word.word}*\n\n"
        f"_{word.meaning}_\n\n"
        f"Example: _{word.example}_"
    )


def send_daily_word(
    db: Optional[Session] = None,
    telegram: Optional[TelegramAdapter] = None,
) -> Tuple[bool, Optional[Word]]:
    """
    Full daily flow: pick a word, send it to Telegram, mark it sent.
    Returns (success, word). Safe to call from a CronJob entrypoint.
    """
    owns_session = db is None
    db = db or get_db_session()
    telegram = telegram or TelegramAdapter()

    try:
        word = get_random_unsent_word(db)
        if word is None:
            return False, None

        message = format_message(word)
        telegram.send_message(message)
        logger.info(f"Sent word to Telegram: {word.word!r}")

        mark_word_sent(db, word.id)
        return True, word
    finally:
        if owns_session:
            db.close()
