"""LLM-backed reminder content generation."""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from html import escape
from typing import Optional, Sequence

from app.adapters.llm_gateway import LLMGatewayAdapter
from app.db.models import Word

logger = logging.getLogger(__name__)


@dataclass
class ReminderContent:
    """Structured reminder content generated for a word."""

    paragraph: str
    history: str
    etymology: str
    cloze_prompt: str = ""


@dataclass(frozen=True)
class ClozeAnswerReveal:
    """A previous fill-in-the-blank answer to show in the next message."""

    word: str
    meaning: str
    prompt: str
    answer: str


@dataclass(frozen=True)
class RenderedReminderMessage:
    """Final message plus structured content worth storing in the DB."""

    message: str
    content: ReminderContent


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


def _parse_reminder_content(raw_content: str, require_cloze: bool = False) -> ReminderContent:
    """Parse the JSON payload the LLM is instructed to return."""
    try:
        payload = json.loads(raw_content)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"LLM returned non-JSON content: {raw_content!r}") from exc

    paragraph = str(payload.get("paragraph", "")).strip()
    history = str(payload.get("history", "")).strip()
    etymology = str(payload.get("etymology", "")).strip()
    cloze_prompt = str(payload.get("cloze_prompt", "")).strip()

    if not paragraph or not history or not etymology:
        raise RuntimeError("LLM response was missing paragraph, history, or etymology.")
    if require_cloze and not cloze_prompt:
        raise RuntimeError("LLM response was missing cloze_prompt.")

    return ReminderContent(
        paragraph=paragraph,
        history=history,
        etymology=etymology,
        cloze_prompt=cloze_prompt,
    )


def _fallback_cloze_prompt(word: Word) -> str:
    """Build a deterministic fill-in-the-blank prompt from stored word data."""
    pattern = re.compile(re.escape(word.word), flags=re.IGNORECASE)
    prompt = pattern.sub("____", word.example, count=1)
    if prompt != word.example:
        return prompt
    return f"The word meaning {word.meaning!r} is ____."


def _context_word_lines(words: Sequence[Word]) -> str:
    if not words:
        return "None."
    return "\n".join(f"- {word.word}: {word.meaning}" for word in words)


def generate_reminder_content(
    word: Word,
    context_words: Sequence[Word] | None = None,
    cloze_word: Word | None = None,
    llm: Optional[LLMGatewayAdapter] = None,
) -> ReminderContent:
    """
    Ask the LLM to produce richer reminder content for a word.

    The model is grounded with the stored meaning and example so the generated
    paragraph stays aligned with the intended sense of the word. Context words
    are previous words that should quietly reappear as extra encounters.
    """
    llm = llm or LLMGatewayAdapter()
    context_words = list(context_words or [])
    logger.info(
        "Generating reminder content: word=%r language=%s context_words=%s cloze_word=%s llm_model=%s",
        word.word,
        word.language_code,
        len(context_words),
        cloze_word.word if cloze_word is not None else None,
        getattr(llm, "default_model", None),
    )
    cloze_target = (
        f"Word: {cloze_word.word}\n"
        f"Meaning: {cloze_word.meaning}\n"
        f"Existing example: {cloze_word.example}\n\n"
        if cloze_word is not None
        else "None.\n\n"
    )
    response = llm.chat(
        messages=[
            {
                "role": "system",
                "content": (
                    "You write concise vocabulary reminders. Return only valid JSON with "
                    'exactly these keys: "paragraph", "history", "etymology", '
                    '"cloze_prompt".'
                ),
            },
            {
                "role": "user",
                "content": (
                    "Create a vocabulary reminder for this word.\n"
                    f"Word: {word.word}\n"
                    f"Meaning: {word.meaning}\n"
                    f"Existing example: {word.example}\n\n"
                    "Previous words to weave into the new-word paragraph/history if possible:\n"
                    f"{_context_word_lines(context_words)}\n\n"
                    "Fill-in-the-blank review target:\n"
                    f"{cloze_target}"
                    "Requirements:\n"
                    "1. paragraph: 2-4 sentences, naturally use the word in context.\n"
                    "   Include the previous words naturally if they fit. Do not define them.\n"
                    "2. history: 1-2 sentences on notable historical usage, development, "
                    "or how the sense evolved.\n"
                    "3. etymology: 1-2 sentences on the word origin.\n"
                    "4. cloze_prompt: if a fill-in-the-blank target exists, write one natural "
                    "sentence with exactly one blank shown as ____. Do not include the answer. "
                    "If no target exists, use an empty string.\n"
                    "5. Stay faithful to the supplied meanings.\n"
                    "6. Return JSON only, no markdown fences."
                ),
            },
        ],
        temperature=0.4,
    )
    content = _parse_reminder_content(_extract_content(response), require_cloze=cloze_word is not None)
    if cloze_word is not None and not content.cloze_prompt:
        content.cloze_prompt = _fallback_cloze_prompt(cloze_word)
    return content


def _fallback_content(word: Word, cloze_word: Word | None = None) -> ReminderContent:
    return ReminderContent(
        paragraph=word.example,
        history="Historical detail unavailable right now.",
        etymology=word.etymology or "Etymology unavailable right now.",
        cloze_prompt=_fallback_cloze_prompt(cloze_word) if cloze_word is not None else "",
    )


def render_reminder_message(
    word: Word,
    context_words: Sequence[Word] | None = None,
    cloze_word: Word | None = None,
    previous_cloze: ClozeAnswerReveal | None = None,
    llm: Optional[LLMGatewayAdapter] = None,
) -> RenderedReminderMessage:
    """
    Render the Telegram message and keep the structured generated fields.

    Falls back to deterministic content if generation fails, so reminders still
    go out even if the gateway is unavailable.
    """
    started = time.perf_counter()
    logger.info(
        "Rendering reminder message start: word=%r language=%s context_words=%s cloze_word=%s has_previous_cloze=%s",
        word.word,
        word.language_code,
        len(list(context_words or [])),
        cloze_word.word if cloze_word is not None else None,
        previous_cloze is not None,
    )
    used_fallback = False
    try:
        content = generate_reminder_content(
            word,
            context_words=context_words,
            cloze_word=cloze_word,
            llm=llm,
        )
        logger.info(
            "Rendered reminder content via LLM after %.2fs: word=%r paragraph_chars=%s history_chars=%s etymology_chars=%s cloze_chars=%s",
            time.perf_counter() - started,
            word.word,
            len(content.paragraph),
            len(content.history),
            len(content.etymology),
            len(content.cloze_prompt),
        )
    except Exception as exc:
        logger.warning(
            "Falling back to static reminder content for %r after %.2fs: %s",
            word.word,
            time.perf_counter() - started,
            exc,
        )
        content = _fallback_content(word, cloze_word=cloze_word)
        used_fallback = True

    parts: list[str] = []
    if previous_cloze is not None:
        parts.append(
            "<b>Previous Blank Answer</b>\n\n"
            f"{_html(previous_cloze.prompt)}\n\n"
            f"<b>Answer:</b> {_html(previous_cloze.answer)} "
            f"({_html(previous_cloze.meaning)})"
        )

    parts.append(
        "📖 <b>Word of the Day</b>\n\n"
        f"<b>{_html(word.word)}</b>\n\n"
        f"<b>Meaning:</b> {_html(word.meaning)}\n\n"
        f"<b>Example Paragraph:</b> {_html(content.paragraph)}\n\n"
        f"<b>History:</b> {_html(content.history)}\n\n"
        f"<b>Etymology:</b> {_html(content.etymology)}"
    )

    if cloze_word is not None and content.cloze_prompt:
        parts.append(
            "<b>Blank for Tomorrow</b>\n\n"
            f"{_html(content.cloze_prompt)}\n\n"
            "Try to guess the missing word; the answer will show up next time."
        )

    message = "\n\n".join(parts)
    logger.info(
        "Rendering reminder message complete after %.2fs: word=%r message_chars=%s used_fallback=%s",
        time.perf_counter() - started,
        word.word,
        len(message),
        used_fallback,
    )
    return RenderedReminderMessage(message=message, content=content)


def build_reminder_message(
    word: Word,
    context_words: Sequence[Word] | None = None,
    cloze_word: Word | None = None,
    previous_cloze: ClozeAnswerReveal | None = None,
    llm: Optional[LLMGatewayAdapter] = None,
) -> str:
    """
    Render the Telegram message for a reminder.

    Compatibility wrapper for callers that only need the message text.
    """
    return render_reminder_message(
        word,
        context_words=context_words,
        cloze_word=cloze_word,
        previous_cloze=previous_cloze,
        llm=llm,
    ).message
