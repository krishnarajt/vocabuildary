"""
Vocabuildary — long-running service entrypoint.

Layout mirrors LLMGateway's main.py: set up logging on import, do startup
work (DB init + one-time import from words.csv), register the APScheduler
job, then wait on a shutdown event so the pod stays alive under k8s.

Scheduling lives here — not in a k8s CronJob — per preference. The cron
expression and timezone are env-configurable (SEND_WORD_CRON + TZ), so
fixing the v1 "9 AM in comment / 3:19 in code" drift is just a value
change in Vault, no code edits required.
"""

import asyncio
import logging
import signal
import sys

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.common import constants
from app.common.logging_config import setup_logging
from app.db.database import init_db
from app.services.dictionary_import_service import mark_stale_import_runs_failed
from app.services.reminder_schedule_service import process_due_reminder_slots
from app.services.word_service import send_daily_words_to_configured_users
from app.ui.server import UIServer
from jobs.import_words import import_words_from_csv


# Configure logging at import time so any downstream logger picks it up
logger = setup_logging(job_name="vocabuildary")


def _run_send_daily_word() -> None:
    """Sync wrapper the scheduler calls — never lets an exception escape."""
    try:
        results = send_daily_words_to_configured_users()
        successes = [result for result in results if result.success]
        failures = [result for result in results if not result.success]
        if successes:
            word = successes[0].word
            logger.info(
                "Scheduled run OK — sent %r to %s recipient(s), %s failure(s)",
                word.word if word else None,
                len(successes),
                len(failures),
            )
        else:
            logger.warning("Scheduled run: no word was sent.")
    except Exception as e:
            logger.error(f"Scheduled run failed: {e}", exc_info=True)


def _run_due_reminder_slots() -> None:
    """Poll user-configured reminder slots and deliver any due messages."""
    try:
        results = process_due_reminder_slots()
        sent = [result for result in results if result.get("sent")]
        if sent:
            logger.info("Reminder slot poll delivered %s message(s)", len(sent))
    except Exception as e:
        logger.error(f"Reminder slot poll failed: {e}", exc_info=True)


async def _amain() -> int:
    logger.info("=" * 60)
    logger.info("Starting Vocabuildary service")
    logger.info("=" * 60)

    # ---- Startup: ensure schema + tables exist ----
    try:
        init_db(use_alembic=True)
        logger.info("✓ Database initialized")
        stale_imports = mark_stale_import_runs_failed()
        if stale_imports:
            logger.warning("Marked %s interrupted import run(s) as failed", stale_imports)
    except Exception as e:
        logger.critical(f"✗ Database init failed: {e}", exc_info=True)
        return 2

    # ---- Startup: idempotent import from words.csv ----
    # Baked into the image; re-running is cheap thanks to ON CONFLICT DO NOTHING.
    try:
        added, skipped = import_words_from_csv(constants.WORDS_CSV_PATH)
        logger.info(
            f"✓ Startup import: {added} new words added, {skipped} duplicates skipped"
        )
    except FileNotFoundError:
        logger.warning(
            f"words.csv not found at {constants.WORDS_CSV_PATH}; skipping startup import."
        )
    except Exception as e:
        # Not fatal — the scheduler can still fire on whatever rows exist
        logger.error(f"Startup import failed (continuing anyway): {e}", exc_info=True)

    # ---- Scheduler ----
    scheduler = AsyncIOScheduler(timezone=constants.TZ)
    try:
        trigger = CronTrigger.from_crontab(constants.SEND_WORD_CRON, timezone=constants.TZ)
    except Exception as e:
        logger.critical(
            f"Invalid SEND_WORD_CRON expression {constants.SEND_WORD_CRON!r}: {e}"
        )
        return 2

    scheduler.add_job(
        _run_send_daily_word,
        id="send_daily_word",
        trigger=trigger,
        name="send_daily_word",
        coalesce=True,         # if we missed fires (pod asleep), collapse to one
        max_instances=1,       # never run two daily-word jobs in parallel
        misfire_grace_time=600,
    )
    scheduler.add_job(
        _run_due_reminder_slots,
        id="due_reminder_slots",
        trigger="interval",
        seconds=max(15, constants.REMINDER_SLOT_POLL_SECONDS),
        name="due_reminder_slots",
        coalesce=True,
        max_instances=1,
        misfire_grace_time=600,
    )
    scheduler.start()
    ui_server = UIServer(port=8000)
    ui_server.start()

    job = scheduler.get_job("send_daily_word")
    next_run = job.next_run_time if job else None
    logger.info(
        f"✓ Scheduler started — cron={constants.SEND_WORD_CRON!r} "
        f"tz={constants.TZ} next_run={next_run}"
    )
    logger.info("✓ UI server started — port=8000")
    logger.info("=" * 60)
    logger.info("Vocabuildary is ready.")
    logger.info("=" * 60)

    # ---- Wait for shutdown ----
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            # Windows / some restricted envs — fall back to default KeyboardInterrupt behaviour
            pass

    try:
        await stop_event.wait()
    finally:
        logger.info("=" * 60)
        logger.info("Shutdown signal received — stopping scheduler and UI server...")
        scheduler.shutdown(wait=False)
        ui_server.stop()
        logger.info("Vocabuildary stopped.")
        logger.info("=" * 60)

    return 0


def main() -> int:
    return asyncio.run(_amain())


if __name__ == "__main__":
    sys.exit(main())
