"""
Shared logging configuration. Mirrors the LLMGateway style:
console + daily-rotating file handlers, noisy libraries muted.
Used by all job entrypoints.
"""

import logging
import os
import sys
from datetime import datetime

from app.common import constants


def setup_logging(job_name: str = "vocabuildary") -> logging.Logger:
    """Configure application-wide logging and return a named logger."""
    log_level = constants.LOG_LEVEL

    # Make sure log directory exists (non-fatal if we can't create it —
    # k8s pods may not have write access; fall back to stdout only).
    file_handler_ok = True
    try:
        os.makedirs(constants.LOG_DIR, exist_ok=True)
    except Exception:
        file_handler_ok = False

    handlers = [logging.StreamHandler(sys.stdout)]
    if file_handler_ok:
        handlers.append(
            logging.FileHandler(
                f"{constants.LOG_DIR}/{job_name}_{datetime.now().strftime('%Y%m%d')}.log",
                encoding="utf-8",
            )
        )

    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=handlers,
        force=True,  # override any prior config from imported libs
    )

    # Mute noisy libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    logger = logging.getLogger(job_name)
    logger.info(f"Logging configured at {log_level} level")
    return logger
