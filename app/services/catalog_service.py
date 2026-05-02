"""Language and word catalog queries for the UI."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.common import constants
from app.db.models import Book, BookWord, Language, Word


class CatalogValidationError(ValueError):
    """Raised when catalog input is not valid."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def normalize_language_code(value: Any, default: str | None = None) -> str:
    text = str(value or "").strip().lower().replace("_", "-")
    if not text:
        text = default or constants.DEFAULT_TARGET_LANGUAGE_CODE
    if len(text) > 32 or any(character.isspace() for character in text):
        raise CatalogValidationError("Language code must be a compact code like en or es.")
    return text


def language_name_from_code(code: str) -> str:
    common_names = {
        "en": "English",
        "es": "Spanish",
        "fr": "French",
        "de": "German",
        "it": "Italian",
        "pt": "Portuguese",
        "hi": "Hindi",
        "ja": "Japanese",
        "ko": "Korean",
        "zh": "Chinese",
    }
    return common_names.get(code, code)


def ensure_language(
    db: Session,
    code: str,
    name: str | None = None,
    native_name: str | None = None,
    notes: str | None = None,
) -> Language:
    normalized_code = normalize_language_code(code)
    language = db.get(Language, normalized_code)
    now = _utcnow()
    if language is None:
        language = Language(
            code=normalized_code,
            name=(name or language_name_from_code(normalized_code)).strip(),
            native_name=(native_name or "").strip() or None,
            notes=(notes or "").strip() or None,
            updated_at=now,
        )
        db.add(language)
        db.flush()
        return language

    if name:
        language.name = name.strip()
    if native_name is not None:
        language.native_name = native_name.strip() or None
    if notes is not None:
        language.notes = notes.strip() or None
    language.updated_at = now
    return language


def list_languages(db: Session) -> list[dict[str, Any]]:
    word_counts = dict(
        db.execute(
            select(Word.language_code, func.count(Word.id))
            .group_by(Word.language_code)
        ).all()
    )
    frequency_counts = dict(
        db.execute(
            select(Word.language_code, func.count(Word.id))
            .where(Word.frequency_rank.is_not(None))
            .group_by(Word.language_code)
        ).all()
    )
    book_counts = dict(
        db.execute(
            select(Book.language_code, func.count(Book.id))
            .group_by(Book.language_code)
        ).all()
    )

    existing_codes = set(word_counts) | set(book_counts) | {constants.DEFAULT_TARGET_LANGUAGE_CODE}
    for code in sorted(existing_codes):
        ensure_language(db, code)
    db.commit()

    languages = db.execute(select(Language).order_by(Language.name.asc(), Language.code.asc())).scalars()
    return [
        {
            "code": language.code,
            "name": language.name,
            "native_name": language.native_name or "",
            "notes": language.notes or "",
            "word_count": int(word_counts.get(language.code, 0) or 0),
            "frequency_count": int(frequency_counts.get(language.code, 0) or 0),
            "book_count": int(book_counts.get(language.code, 0) or 0),
            "created_at": language.created_at.isoformat() if language.created_at else None,
            "updated_at": language.updated_at.isoformat() if language.updated_at else None,
        }
        for language in languages
    ]


def create_language(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    code = normalize_language_code(payload.get("code"))
    name = str(payload.get("name") or language_name_from_code(code)).strip()
    if not name:
        raise CatalogValidationError("Language name is required.")
    language = ensure_language(
        db,
        code,
        name=name,
        native_name=str(payload.get("native_name") or "").strip() or None,
        notes=str(payload.get("notes") or "").strip() or None,
    )
    db.commit()
    return {
        "code": language.code,
        "name": language.name,
        "native_name": language.native_name or "",
        "notes": language.notes or "",
        "word_count": 0,
        "frequency_count": 0,
        "book_count": 0,
        "created_at": language.created_at.isoformat() if language.created_at else None,
        "updated_at": language.updated_at.isoformat() if language.updated_at else None,
    }


def search_words(
    db: Session,
    query: str = "",
    language_code: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    limit = max(1, min(int(limit or 50), 200))
    offset = max(0, int(offset or 0))
    normalized_query = (query or "").strip()
    normalized_language = normalize_language_code(language_code) if language_code else None

    stmt = select(Word)
    count_stmt = select(func.count()).select_from(Word)
    filters = []
    if normalized_language:
        filters.append(Word.language_code == normalized_language)
    if normalized_query:
        pattern = f"%{normalized_query}%"
        filters.append(
            or_(
                Word.word.ilike(pattern),
                Word.meaning.ilike(pattern),
                Word.part_of_speech.ilike(pattern),
            )
        )
    for filter_clause in filters:
        stmt = stmt.where(filter_clause)
        count_stmt = count_stmt.where(filter_clause)

    stmt = (
        stmt.order_by(Word.frequency_rank.asc().nullslast(), Word.word.asc())
        .limit(limit)
        .offset(offset)
    )
    words = list(db.execute(stmt).scalars())
    total = int(db.execute(count_stmt).scalar_one() or 0)

    book_counts = {}
    if words:
        book_counts = dict(
            db.execute(
                select(BookWord.word_id, func.count(func.distinct(BookWord.book_id)))
                .where(BookWord.word_id.in_([word.id for word in words]))
                .group_by(BookWord.word_id)
            ).all()
        )

    return {
        "items": [serialize_word(word, book_count=int(book_counts.get(word.id, 0) or 0)) for word in words],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


def serialize_word(word: Word, book_count: int = 0) -> dict[str, Any]:
    return {
        "id": word.id,
        "language_code": word.language_code,
        "word": word.word,
        "meaning": word.meaning or "",
        "example": word.example or "",
        "part_of_speech": word.part_of_speech or "",
        "pronunciation": word.pronunciation or "",
        "origin_language": word.origin_language or "",
        "etymology": word.etymology or "",
        "register": word.register or "",
        "difficulty_level": word.difficulty_level,
        "frequency_rank": word.frequency_rank,
        "frequency_score": word.frequency_score,
        "zipf_frequency": word.zipf_frequency,
        "frequency_source": word.frequency_source or "",
        "definition_source": word.definition_source or "",
        "frequency_updated_at": word.frequency_updated_at.isoformat()
        if word.frequency_updated_at
        else None,
        "definition_updated_at": word.definition_updated_at.isoformat()
        if word.definition_updated_at
        else None,
        "metadata": word.word_metadata or {},
        "book_count": book_count,
    }
