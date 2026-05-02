"""
Entrypoint for the one-shot words.csv import Job.

Run as: `python -m jobs.import_words`

Equivalent to v1's import_words.py but on SQLAlchemy + Postgres. Uses
ON CONFLICT DO NOTHING via SQLAlchemy dialect so re-running is safe.
"""

import csv
import logging
import sys

from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.common import constants
from app.common.logging_config import setup_logging
from app.db.database import get_db_session, init_db
from app.db.models import Word


logger = logging.getLogger(__name__)


def import_words_from_csv(csv_path: str) -> tuple[int, int]:
    """Upsert rows from csv_path. Returns (added, skipped)."""
    added = 0
    skipped = 0

    db = get_db_session()
    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Expecting columns: word, meaning, example. Richer dictionaries
                # may also include language_code, pronunciation, etymology, etc.
                language_code = (
                    row.get("language_code")
                    or row.get("language")
                    or constants.DEFAULT_TARGET_LANGUAGE_CODE
                ).strip()
                word_value = (row.get("word") or "").strip()
                meaning_value = (row.get("meaning") or "").strip()
                example_value = (row.get("example") or "").strip()
                if not word_value:
                    continue

                stmt = (
                    pg_insert(Word)
                    .values(
                        language_code=language_code,
                        word=word_value,
                        meaning=meaning_value,
                        example=example_value,
                        part_of_speech=(row.get("part_of_speech") or "").strip() or None,
                        pronunciation=(row.get("pronunciation") or "").strip() or None,
                        origin_language=(row.get("origin_language") or "").strip() or None,
                        etymology=(row.get("etymology") or "").strip() or None,
                        register=(row.get("register") or "").strip() or None,
                        difficulty_level=int(row["difficulty_level"])
                        if (row.get("difficulty_level") or "").strip().isdigit()
                        else None,
                        sent=False,
                    )
                    .on_conflict_do_nothing(index_elements=["language_code", "word"])
                )
                result = db.execute(stmt)
                # rowcount == 1 means we actually inserted; 0 means skipped
                if result.rowcount == 1:
                    added += 1
                else:
                    skipped += 1
        db.commit()
    finally:
        db.close()

    return added, skipped


def main() -> int:
    logger_local = setup_logging(job_name="import_words")
    logger_local.info("=" * 60)
    logger_local.info("Vocabuildary import_words job starting")
    logger_local.info(f"CSV path: {constants.WORDS_CSV_PATH}")
    logger_local.info("=" * 60)

    try:
        init_db(use_alembic=True)
    except Exception as e:
        logger_local.critical(f"Database init failed: {e}", exc_info=True)
        return 2

    try:
        added, skipped = import_words_from_csv(constants.WORDS_CSV_PATH)
        logger_local.info(
            f"✅ Import complete: {added} new words added, {skipped} duplicates skipped."
        )
        return 0
    except FileNotFoundError:
        logger_local.error(f"CSV file not found at {constants.WORDS_CSV_PATH}")
        return 4
    except Exception as e:
        logger_local.error(f"import_words failed: {e}", exc_info=True)
        return 3


if __name__ == "__main__":
    sys.exit(main())
