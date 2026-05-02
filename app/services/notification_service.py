"""Notification provider selection for Vocabuildary sends."""

from __future__ import annotations

from typing import Protocol, TYPE_CHECKING

from app.adapters.apprise import AppriseAdapter
from app.adapters.telegram import TelegramAdapter
from app.common import constants

if TYPE_CHECKING:
    from app.db.models import VocabuildaryUser


class NotificationSender(Protocol):
    def send_message(
        self,
        text: str,
        parse_mode: str = "HTML",
        disable_web_page_preview: bool = True,
    ) -> dict:
        ...


def normalize_notification_provider(value: object) -> str:
    return "apprise" if str(value or "").strip().lower() == "apprise" else "telegram"


def create_notifier_for_user(user: "VocabuildaryUser") -> NotificationSender:
    provider = normalize_notification_provider(user.notification_provider)
    if provider == "apprise":
        return AppriseAdapter(urls=user.apprise_urls)
    return TelegramAdapter(
        bot_token=user.telegram_bot_token,
        chat_id=user.telegram_chat_id,
    )


def legacy_notification_configured() -> bool:
    provider = normalize_notification_provider(constants.NOTIFICATION_PROVIDER)
    if provider == "apprise":
        return bool(constants.APPRISE_URLS.strip())
    if constants.TELEGRAM_BOT_TOKEN and constants.TELEGRAM_CHAT_ID:
        return True
    return bool(constants.APPRISE_URLS.strip())


def create_legacy_notifier() -> NotificationSender:
    provider = normalize_notification_provider(constants.NOTIFICATION_PROVIDER)
    if provider == "apprise" or (
        not (constants.TELEGRAM_BOT_TOKEN and constants.TELEGRAM_CHAT_ID)
        and constants.APPRISE_URLS.strip()
    ):
        return AppriseAdapter()
    return TelegramAdapter()


def notification_provider_label(provider: object) -> str:
    return "Apprise" if normalize_notification_provider(provider) == "apprise" else "Telegram"
