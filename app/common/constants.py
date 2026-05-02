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

# ===== Database =====
# A fully-formed URL lives in Vault and is injected via the External Secret.
# Example value:
#   postgresql+psycopg://vocabuildary:<pw>@postgres-host:5432/vocabuildary
DATABASE_URL: str = _get_required("DATABASE_URL")
DB_SCHEMA: str = os.getenv("DB_SCHEMA", "vocabuildary")

# ===== Telegram =====
TELEGRAM_BOT_TOKEN: str = _get_required("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID: str = _get_required("TELEGRAM_CHAT_ID")

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
