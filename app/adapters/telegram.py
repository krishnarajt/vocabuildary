"""
Telegram Bot API adapter.

Thin, synchronous httpx client — we only need sendMessage for now and
the jobs are short-lived scripts, so async buys us nothing here.
"""

import logging
from typing import Optional

import httpx

from app.common import constants

logger = logging.getLogger(__name__)


class TelegramAdapter:
    """Minimal Telegram Bot API client."""

    def __init__(
        self,
        bot_token: Optional[str] = None,
        chat_id: Optional[str] = None,
        timeout: float = 10.0,
    ) -> None:
        self.bot_token = bot_token or constants.TELEGRAM_BOT_TOKEN
        self.chat_id = chat_id or constants.TELEGRAM_CHAT_ID
        if not self.bot_token or not self.chat_id:
            raise RuntimeError(
                "Telegram bot token and chat id are required. Configure them "
                "for the signed-in user in Vocabuildary."
            )
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}"
        self.timeout = timeout

    def send_message(
        self,
        text: str,
        parse_mode: str = "Markdown",
        disable_web_page_preview: bool = True,
    ) -> dict:
        """Send a message to the configured chat. Raises on HTTP errors."""
        url = f"{self.base_url}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": disable_web_page_preview,
        }
        logger.debug(f"POST {url} chat_id={self.chat_id}")
        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(url, json=payload)
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            # Telegram returns 200 even on logical failures sometimes
            raise RuntimeError(f"Telegram API returned not-ok: {data}")
        return data
