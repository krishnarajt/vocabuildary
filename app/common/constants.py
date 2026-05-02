"""
Central configuration for Vocabuildary.

All environment variables are loaded here and exposed as typed module-level
constants so the rest of the code never calls os.getenv directly.
Mirrors the pattern used in LLMGateway.
"""

import os
from dotenv import load_dotenv

# Load .env if present (no-op inside k8s where env comes from External Secrets)
load_dotenv()


def _get_required(name: str) -> str:
    """Fetch a required env var or fail fast with a clear error."""
    value = os.getenv(name)
    if value is None or value == "":
        raise RuntimeError(
            f"Required environment variable '{name}' is not set. "
            f"Check your .env file or the External Secret bound to the pod."
        )
    return value


# ===== App =====
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_DIR: str = os.getenv("LOG_DIR", "/app/logs")
TZ: str = os.getenv("TZ", "Asia/Kolkata")

# Cron expression (standard 5-field crontab) for when the daily word fires.
# Evaluated inside APScheduler using the TZ above. Default: 09:00 local.
SEND_WORD_CRON: str = os.getenv("SEND_WORD_CRON", "0 9 * * *")
REMINDER_SLOT_POLL_SECONDS: int = int(os.getenv("REMINDER_SLOT_POLL_SECONDS", "60"))

# ===== Database =====
# A fully-formed URL lives in Vault and is injected via the External Secret.
# Example value:
#   postgresql+psycopg://vocabuildary:<pw>@postgres-host:5432/vocabuildary
DATABASE_URL: str = _get_required("DATABASE_URL")
DB_SCHEMA: str = os.getenv("DB_SCHEMA", "vocabuildary")

# ===== Telegram =====
# Legacy fallback only. New installs store Telegram destination settings per
# Authentik user in the database, populated through the UI.
TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")

# ===== Notifications =====
# Per-user delivery is stored in the database. These env values are only used
# by the legacy no-user fallback path.
NOTIFICATION_PROVIDER: str = os.getenv("NOTIFICATION_PROVIDER", "telegram").strip().lower()
APPRISE_URLS: str = os.getenv("APPRISE_URLS", "")
APPRISE_NOTIFICATION_TITLE: str = os.getenv("APPRISE_NOTIFICATION_TITLE", "Vocabuildary")

# ===== Book storage =====
# S3-compatible object storage. The env var names intentionally match the
# Just Like Clockwork backend so both apps can share the same deployment
# convention while using different buckets/prefixes.
MINIO_ENDPOINT: str = os.getenv("MINIO_ENDPOINT", "http://localhost:9000")
MINIO_ACCESS_KEY: str = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY: str = os.getenv("MINIO_SECRET_KEY", "minioadmin")
MINIO_BUCKET: str = os.getenv("MINIO_BUCKET", "vocabuildary-books")
MINIO_REGION: str = os.getenv("MINIO_REGION", "us-east-1")

BOOK_UPLOAD_URL_EXPIRATION_SECONDS: int = int(
    os.getenv("BOOK_UPLOAD_URL_EXPIRATION_SECONDS", "900")
)
BOOK_DOWNLOAD_URL_EXPIRATION_SECONDS: int = int(
    os.getenv("BOOK_DOWNLOAD_URL_EXPIRATION_SECONDS", "3600")
)
MAX_BOOK_UPLOAD_BYTES: int = int(
    os.getenv("MAX_BOOK_UPLOAD_BYTES", str(500 * 1024 * 1024))
)

# ===== LLM Gateway =====
LLM_GATEWAY_URL: str = os.getenv(
    "LLM_GATEWAY_URL",
    "https://llmgateway.krishnarajthadesar.in",
)
LLM_GATEWAY_API_KEY: str = os.getenv("LLM_GATEWAY_API_KEY", "")
LLM_GATEWAY_DEFAULT_MODEL: str = os.getenv(
    "LLM_GATEWAY_DEFAULT_MODEL",
    "gemini-flash-latest",
)
# Path on the gateway that speaks the native LLMGateway chat protocol.
LLM_GATEWAY_CHAT_PATH: str = os.getenv(
    "LLM_GATEWAY_CHAT_PATH",
    "/api/chat",
)

# ===== Import job =====
# Path to the CSV file consumed by the startup importer / jobs/import_words.py.
# Baked into the image at build time by default.
WORDS_CSV_PATH: str = os.getenv("WORDS_CSV_PATH", "/app/words.csv")

# UI-triggered dictionary imports. Frequency data is intentionally separate
# from definitions so the app can ingest a broad word catalog first and enrich
# meanings later.
FREQUENCY_IMPORT_WORDLIST: str = os.getenv("FREQUENCY_IMPORT_WORDLIST", "best")
FREQUENCY_IMPORT_MAX_WORDS: int = int(os.getenv("FREQUENCY_IMPORT_MAX_WORDS", "2000000"))
FREQUENCY_IMPORT_BATCH_SIZE: int = int(os.getenv("FREQUENCY_IMPORT_BATCH_SIZE", "1000"))

KAIKKI_ENGLISH_JSONL_URL: str = os.getenv(
    "KAIKKI_ENGLISH_JSONL_URL",
    "https://kaikki.org/dictionary/English/kaikki.org-dictionary-English.jsonl",
)
KAIKKI_IMPORT_CHUNK_COUNT: int = int(os.getenv("KAIKKI_IMPORT_CHUNK_COUNT", "10"))
KAIKKI_IMPORT_TOTAL_ESTIMATE: int = int(os.getenv("KAIKKI_IMPORT_TOTAL_ESTIMATE", "1709154"))
KAIKKI_IMPORT_BATCH_SIZE: int = int(os.getenv("KAIKKI_IMPORT_BATCH_SIZE", "500"))
KAIKKI_IMPORT_TIMEOUT_SECONDS: int = int(os.getenv("KAIKKI_IMPORT_TIMEOUT_SECONDS", "3600"))

# ===== Learning schedule defaults =====
# These are only defaults for newly-created per-user settings. Users can tune
# their own reminder cadence in the database/UI without changing the global
# dictionary rows.
DEFAULT_DAILY_REVIEW_WORDS: int = int(os.getenv("DEFAULT_DAILY_REVIEW_WORDS", "3"))
DEFAULT_DAILY_CLOZE_WORDS: int = int(os.getenv("DEFAULT_DAILY_CLOZE_WORDS", "1"))
DEFAULT_MASTERY_ENCOUNTERS: int = int(os.getenv("DEFAULT_MASTERY_ENCOUNTERS", "8"))
DEFAULT_TARGET_LANGUAGE_CODE: str = os.getenv("DEFAULT_TARGET_LANGUAGE_CODE", "en")


def _parse_review_intervals(value: str) -> list[int]:
    intervals: list[int] = []
    for raw_part in value.split(","):
        part = raw_part.strip()
        if not part:
            continue
        try:
            interval = int(part)
        except ValueError:
            continue
        if interval > 0:
            intervals.append(interval)
    return intervals or [1, 3, 7, 14, 30, 60, 120]


DEFAULT_REVIEW_INTERVAL_DAYS: list[int] = _parse_review_intervals(
    os.getenv("DEFAULT_REVIEW_INTERVAL_DAYS", "1,3,7,14,30,60,120")
)
