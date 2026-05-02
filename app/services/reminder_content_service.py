"""LLM-backed reminder content generation."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from html import escape
from typing import Optional

from app.adapters.llm_gateway import LLMGatewayAdapter
from app.db.models import Word

logger = logging.getLogger(__name__)


@dataclass
class ReminderContent:
    """Structured reminder content generated for a word."""

    paragraph: str
    history: str
    etymology: str


def _html(text: str) -> str:
    """Escape text for Telegram HTML parse mode."""
    return escape(text, quote=False)


def _extract_content(response: dict) -> str:
    """Pull the assistant text out of a gateway or OpenAI-style chat response."""
    content = response.get("content")
    if isinstance(content, str):
        return content.strip()

    try:
        return response["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("LLM response did not contain message content.") from exc


def _parse_reminder_content(raw_content: str) -> ReminderContent:
    """Parse the JSON payload the LLM is instructed to return."""
    try:
        payload = json.loads(raw_content)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"LLM returned non-JSON content: {raw_content!r}") from exc

    paragraph = str(payload.get("paragraph", "")).strip()
    history = str(payload.get("history", "")).strip()
    etymology = str(payload.get("etymology", "")).strip()

    if not paragraph or not history or not etymology:
        raise RuntimeError("LLM response was missing paragraph, history, or etymology.")

    return ReminderContent(paragraph=paragraph, history=history, etymology=etymology)


def generate_reminder_content(
    word: Word,
    llm: Optional[LLMGatewayAdapter] = None,
) -> ReminderContent:
    """
    Ask the LLM to produce richer reminder content for a word.

    The model is grounded with the stored meaning and example so the generated
    paragraph stays aligned with the intended sense of the word.
    """
    llm = llm or LLMGatewayAdapter()
    response = llm.chat(
        messages=[
            {
                "role": "system",
                "content": (
                    "You write concise vocabulary reminders. Return only valid JSON with "
                    'exactly these keys: "paragraph", "history", "etymology".'
                ),
            },
            {
                "role": "user",
                "content": (
                    "Create a vocabulary reminder for this word.\n"
                    f"Word: {word.word}\n"
                    f"Meaning: {word.meaning}\n"
                    f"Existing example: {word.example}\n\n"
                    "Requirements:\n"
                    "1. paragraph: 2-4 sentences, naturally use the word in context.\n"
                    "2. history: 1-2 sentences on notable historical usage, development, "
                    "or how the sense evolved.\n"
                    "3. etymology: 1-2 sentences on the word origin.\n"
                    "4. Stay faithful to the supplied meaning.\n"
                    "5. Return JSON only, no markdown fences."
                ),
            },
        ],
        temperature=0.4,
    )
    return _parse_reminder_content(_extract_content(response))


def build_reminder_message(
    word: Word,
    llm: Optional[LLMGatewayAdapter] = None,
) -> str:
    """
    Render the Telegram message for a reminder.

    Falls back to a deterministic non-LLM version if content generation fails,
    so reminders still go out even if the gateway is unavailable.
    """
    try:
        content = generate_reminder_content(word, llm=llm)
    except Exception as exc:
        logger.warning("Falling back to static reminder content for %r: %s", word.word, exc)
        return (
            "📖 <b>Word of the Day</b>\n\n"
            f"<b>{_html(word.word)}</b>\n\n"
            f"<b>Meaning:</b> {_html(word.meaning)}\n\n"
            f"<b>Example Paragraph:</b> {_html(word.example)}\n\n"
            "<b>History:</b> Historical detail unavailable right now.\n\n"
            "<b>Etymology:</b> Etymology unavailable right now."
        )

    return (
        "📖 <b>Word of the Day</b>\n\n"
        f"<b>{_html(word.word)}</b>\n\n"
        f"<b>Meaning:</b> {_html(word.meaning)}\n\n"
        f"<b>Example Paragraph:</b> {_html(content.paragraph)}\n\n"
        f"<b>History:</b> {_html(content.history)}\n\n"
        f"<b>Etymology:</b> {_html(content.etymology)}"
    )
