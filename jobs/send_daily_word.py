"""
Entrypoint for the daily-word CronJob.

Run as: `python -m jobs.send_daily_word`

Kubernetes CronJob (with spec.timeZone) handles scheduling. This script
runs once, does the work, and exits. That fixes the v1 problem where
APScheduler lived inside a long-running process and the cron expression
had drifted (9 AM in comment vs 3:19 AM in code).
"""

import sys

from app.common.logging_config import setup_logging
from app.db.database import init_db
from app.services.word_service import send_daily_word


def main() -> int:
    logger = setup_logging(job_name="send_daily_word")
    logger.info("=" * 60)
    logger.info("Vocabuildary daily-word job starting")
    logger.info("=" * 60)

    try:
        # Idempotent — creates the words table on first run.
        init_db()
    except Exception as e:
        logger.critical(f"Database init failed: {e}", exc_info=True)
        return 2

    try:
        success, word = send_daily_word()
        if not success:
            logger.warning("No word was sent (empty table?).")
            return 1
        logger.info(f"Done. Sent: {word.word!r}")
        return 0
    except Exception as e:
        logger.error(f"send_daily_word failed: {e}", exc_info=True)
        return 3


if __name__ == "__main__":
    sys.exit(main())
