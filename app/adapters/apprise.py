"""Apprise notification adapter."""

from __future__ import annotations

import logging
from typing import Iterable

from app.common import constants

try:
    import apprise
except ImportError:  # pragma: no cover - exercised only in missing dependency installs
    apprise = None

logger = logging.getLogger(__name__)


def normalize_apprise_urls(value: object) -> list[str]:
    """Normalize newline-delimited Apprise URLs from env, DB, or API payloads."""
    if value is None:
        return []
    if isinstance(value, str):
        text = value.replace("\r\n", "\n").replace("\r", "\n")
        urls = [line.strip() for line in text.split("\n") if line.strip()]
        if len(urls) == 1 and "," in urls[0]:
            urls = [part.strip() for part in urls[0].split(",") if part.strip()]
        return urls
    if isinstance(value, Iterable):
        urls = []
        for item in value:
            item_text = str(item or "").strip()
            if item_text:
                urls.append(item_text)
        return urls
    return []


class AppriseAdapter:
    """Minimal Apprise client matching the TelegramAdapter send surface."""

    def __init__(
        self,
        urls: object = None,
        title: str | None = None,
    ) -> None:
        if apprise is None:
            raise RuntimeError("The apprise package is required for Apprise notifications.")
        self.urls = normalize_apprise_urls(urls if urls is not None else constants.APPRISE_URLS)
        if not self.urls:
            raise RuntimeError("At least one Apprise URL is required.")
        self.title = title or constants.APPRISE_NOTIFICATION_TITLE

    def send_message(
        self,
        text: str,
        parse_mode: str = "HTML",
        disable_web_page_preview: bool = True,
    ) -> dict:
        """Send a message through all configured Apprise URLs."""
        notifier = apprise.Apprise()
        for url in self.urls:
            if not notifier.add(url):
                raise RuntimeError("Apprise rejected one of the configured URLs.")

        body_format = apprise.NotifyFormat.HTML
        if str(parse_mode or "").lower() in {"markdown", "md"}:
            body_format = apprise.NotifyFormat.MARKDOWN
        elif str(parse_mode or "").lower() in {"text", "plain"}:
            body_format = apprise.NotifyFormat.TEXT

        logger.debug("Sending Apprise notification to %s URL(s)", len(self.urls))
        ok = notifier.notify(body=text, title=self.title, body_format=body_format)
        if not ok:
            raise RuntimeError("Apprise notification delivery failed.")
        return {"ok": True, "provider": "apprise", "targets": len(self.urls)}
