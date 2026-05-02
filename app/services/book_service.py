"""Business logic for book uploads, processing, and public API payloads."""

from __future__ import annotations

import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.common import constants
from app.db.models import Book, BookWord, VocabuildaryUser, Word
from app.services.catalog_service import ensure_language, normalize_language_code
from app.services.book_storage_service import (
    BookStorageService,
    BookValidationError,
    build_source_object_key,
    build_word_map_object_key,
    get_book_storage_service,
    infer_content_type,
    s3_uri,
    validate_book_upload_request,
)
from app.services.book_text_extraction import count_words, extract_text_from_book

BOOK_STATUS_UPLOAD_PENDING = "upload_pending"
BOOK_STATUS_UPLOADED = "uploaded"
BOOK_STATUS_PROCESSING = "processing"
BOOK_STATUS_PROCESSED = "processed"
BOOK_STATUS_FAILED = "failed"


class BookNotFoundError(LookupError):
    """Raised when a book does not exist for the current user."""


class BookProcessingError(RuntimeError):
    """Raised when processing cannot complete."""


def _clean_optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _clean_optional_int(value: Any, field_name: str) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise BookValidationError(f"{field_name} must be a number.") from exc


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _book_display_name(book: Book) -> str:
    return book.title or book.original_filename


def _book_language_code(payload: dict[str, Any]) -> str:
    raw_code = payload.get("language_code")
    if raw_code:
        return normalize_language_code(raw_code)

    raw_language = str(payload.get("language") or "").strip().lower()
    language_names = {
        "english": "en",
        "spanish": "es",
        "french": "fr",
        "german": "de",
        "italian": "it",
        "portuguese": "pt",
        "hindi": "hi",
        "japanese": "ja",
        "korean": "ko",
        "chinese": "zh",
    }
    if raw_language in language_names:
        return language_names[raw_language]
    if raw_language:
        return normalize_language_code(raw_language)
    return constants.DEFAULT_TARGET_LANGUAGE_CODE


def create_book_upload(
    db: Session,
    user: VocabuildaryUser,
    payload: dict[str, Any],
    storage: BookStorageService | None = None,
) -> tuple[Book, dict[str, Any]]:
    """Create a pending book row and return a presigned PUT target."""
    filename = str(payload.get("filename") or "").strip()
    file_size_int = _clean_optional_int(payload.get("file_size"), "file_size")
    extension = validate_book_upload_request(filename, file_size_int)
    content_type = infer_content_type(filename, _clean_optional_text(payload.get("content_type")))
    book_uuid = str(uuid.uuid4())
    language_code = _book_language_code(payload)
    storage = storage or get_book_storage_service()
    source_object_key = build_source_object_key(user.id, book_uuid, filename)

    upload_url = storage.generate_presigned_put_url(source_object_key, content_type)

    book = Book(
        book_uuid=book_uuid,
        user_id=user.id,
        title=_clean_optional_text(payload.get("title")),
        isbn=_clean_optional_text(payload.get("isbn")),
        author=_clean_optional_text(payload.get("author")),
        language=_clean_optional_text(payload.get("language")),
        language_code=language_code,
        notes=_clean_optional_text(payload.get("notes")),
        original_filename=filename,
        file_extension=extension,
        mime_type=content_type,
        file_size=file_size_int,
        source_bucket=storage.bucket_name,
        source_object_key=source_object_key,
        status=BOOK_STATUS_UPLOAD_PENDING,
        learning_enabled=bool(payload.get("learning_enabled", False)),
        updated_at=_utcnow(),
    )
    db.add(book)
    db.commit()
    db.refresh(book)

    return book, {
        "method": "PUT",
        "url": upload_url,
        "expires_in": constants.BOOK_UPLOAD_URL_EXPIRATION_SECONDS,
        "headers": {"Content-Type": content_type},
    }


def get_book_for_user(db: Session, user: VocabuildaryUser, book_id: int) -> Book:
    stmt = select(Book).where(Book.id == book_id, Book.user_id == user.id)
    book = db.execute(stmt).scalar_one_or_none()
    if book is None:
        raise BookNotFoundError("Book not found.")
    return book


def list_books_for_user(db: Session, user: VocabuildaryUser) -> list[Book]:
    stmt = (
        select(Book)
        .where(Book.user_id == user.id)
        .order_by(Book.created_at.desc(), Book.id.desc())
    )
    return list(db.execute(stmt).scalars())


def mark_book_upload_complete(
    db: Session,
    user: VocabuildaryUser,
    book_id: int,
    payload: dict[str, Any] | None = None,
) -> Book:
    book = get_book_for_user(db, user, book_id)
    payload = payload or {}
    if "file_size" in payload and payload.get("file_size") is not None:
        book.file_size = _clean_optional_int(payload["file_size"], "file_size")
    book.status = BOOK_STATUS_UPLOADED
    book.processing_error = None
    book.uploaded_at = _utcnow()
    book.updated_at = _utcnow()
    db.commit()
    db.refresh(book)
    return book


def process_book(
    db: Session,
    user: VocabuildaryUser,
    book_id: int,
    storage: BookStorageService | None = None,
) -> Book:
    """Download a source book, count words, upload the JSON map, and update DB state."""
    book = get_book_for_user(db, user, book_id)
    if book.status == BOOK_STATUS_UPLOAD_PENDING:
        raise BookValidationError("Upload the source document before processing the book.")

    storage = storage or get_book_storage_service()
    book.status = BOOK_STATUS_PROCESSING
    book.processing_error = None
    book.updated_at = _utcnow()
    db.commit()

    try:
        with tempfile.TemporaryDirectory(prefix="vocabuildary-book-") as tempdir:
            source_path = Path(tempdir) / f"source.{book.file_extension}"
            storage.download_object_to_file(book.source_object_key, source_path)
            text = extract_text_from_book(source_path, book.file_extension)
            word_map = count_words(text)
            word_map_key = build_word_map_object_key(book.user_id, book.book_uuid)
            storage.upload_json(word_map_key, word_map)
            _persist_book_words(db, book, word_map)

        book.word_map_bucket = storage.bucket_name
        book.word_map_object_key = word_map_key
        book.total_words = sum(word_map.values())
        book.unique_words = len(word_map)
        book.status = BOOK_STATUS_PROCESSED
        book.processing_error = None
        book.processed_at = _utcnow()
        book.updated_at = _utcnow()
        db.commit()
        db.refresh(book)
        return book
    except Exception as exc:
        book.status = BOOK_STATUS_FAILED
        book.processing_error = str(exc)
        book.updated_at = _utcnow()
        db.commit()
        raise BookProcessingError(str(exc)) from exc


def _persist_book_words(db: Session, book: Book, word_map: dict[str, int]) -> None:
    """Persist a processed book's word map into canonical words + book_words."""
    language_code = normalize_language_code(book.language_code or book.language)
    ensure_language(db, language_code)
    book.language_code = language_code

    ranked_items = sorted(
        ((word, int(count)) for word, count in word_map.items() if word and int(count) > 0),
        key=lambda item: (-item[1], item[0]),
    )
    if not ranked_items:
        db.execute(delete(BookWord).where(BookWord.book_id == book.id))
        return

    now = _utcnow()
    words = [word for word, _count in ranked_items]
    if db.bind and db.bind.dialect.name == "postgresql":
        rows = [
            {
                "language_code": language_code,
                "word": word,
                "meaning": "",
                "example": "",
                "sent": False,
            }
            for word in words
        ]
        db.execute(
            pg_insert(Word)
            .values(rows)
            .on_conflict_do_nothing(index_elements=["language_code", "word"])
        )
        db.flush()
    else:
        existing = set(
            db.execute(
                select(Word.word).where(Word.language_code == language_code, Word.word.in_(words))
            ).scalars()
        )
        db.add_all(
            [
                Word(language_code=language_code, word=word, meaning="", example="", sent=False)
                for word in words
                if word not in existing
            ]
        )
        db.flush()

    word_ids = dict(
        db.execute(
            select(Word.word, Word.id).where(Word.language_code == language_code, Word.word.in_(words))
        ).all()
    )
    db.execute(delete(BookWord).where(BookWord.book_id == book.id))
    db.flush()

    db.add_all(
        [
            BookWord(
                book_id=book.id,
                word_id=word_ids[word],
                user_id=book.user_id,
                language_code=language_code,
                source_text=word,
                occurrence_count=count,
                rank_in_book=rank,
                updated_at=now,
            )
            for rank, (word, count) in enumerate(ranked_items, start=1)
            if word in word_ids
        ]
    )


def update_book_learning_settings(
    db: Session,
    user: VocabuildaryUser,
    book_id: int,
    payload: dict[str, Any],
) -> Book:
    book = get_book_for_user(db, user, book_id)
    if "learning_enabled" in payload:
        book.learning_enabled = bool(payload.get("learning_enabled"))
    if "language_code" in payload:
        language_code = normalize_language_code(payload.get("language_code"))
        ensure_language(db, language_code)
        book.language_code = language_code
    if "language" in payload:
        book.language = _clean_optional_text(payload.get("language"))
    book.updated_at = _utcnow()
    db.commit()
    db.refresh(book)
    return book


def list_book_words_for_user(
    db: Session,
    user: VocabuildaryUser,
    book_id: int,
    limit: int = 200,
    offset: int = 0,
) -> dict[str, Any]:
    book = get_book_for_user(db, user, book_id)
    limit = max(1, min(int(limit or 200), 500))
    offset = max(0, int(offset or 0))
    total = int(
        db.execute(
            select(func.count())
            .select_from(BookWord)
            .where(BookWord.book_id == book.id)
        ).scalar_one()
        or 0
    )
    rows = (
        db.execute(
            select(BookWord, Word)
            .join(Word, Word.id == BookWord.word_id)
            .where(BookWord.book_id == book.id)
            .order_by(BookWord.rank_in_book.asc().nullslast(), Word.word.asc())
            .limit(limit)
            .offset(offset)
        )
        .all()
    )
    return {
        "book": serialize_book(book),
        "items": [serialize_book_word(book_word, word) for book_word, word in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


def get_processed_word_map_url(
    db: Session,
    user: VocabuildaryUser,
    book_id: int,
    storage: BookStorageService | None = None,
) -> tuple[Book, str]:
    book = get_book_for_user(db, user, book_id)
    if book.status != BOOK_STATUS_PROCESSED or not book.word_map_object_key:
        raise BookValidationError("The book has not been processed yet.")

    storage = storage or get_book_storage_service()
    url = storage.generate_presigned_get_url(book.word_map_object_key)
    return book, url


def _serialize_datetime(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return value.isoformat()


def serialize_book(book: Book) -> dict[str, Any]:
    return {
        "id": book.id,
        "book_uuid": book.book_uuid,
        "name": _book_display_name(book),
        "title": book.title or "",
        "isbn": book.isbn or "",
        "author": book.author or "",
        "language": book.language or "",
        "language_code": getattr(book, "language_code", None) or constants.DEFAULT_TARGET_LANGUAGE_CODE,
        "notes": book.notes or "",
        "status": book.status,
        "learning_enabled": bool(getattr(book, "learning_enabled", False)),
        "processing_error": book.processing_error,
        "source": {
            "filename": book.original_filename,
            "file_extension": book.file_extension,
            "mime_type": book.mime_type,
            "file_size": book.file_size,
            "bucket": book.source_bucket,
            "object_key": book.source_object_key,
            "s3_uri": s3_uri(book.source_bucket, book.source_object_key),
        },
        "processed": {
            "bucket": book.word_map_bucket,
            "object_key": book.word_map_object_key,
            "s3_uri": s3_uri(book.word_map_bucket, book.word_map_object_key),
            "total_words": book.total_words or 0,
            "unique_words": book.unique_words or 0,
            "processed_at": _serialize_datetime(book.processed_at),
        },
        "created_at": _serialize_datetime(book.created_at),
        "updated_at": _serialize_datetime(book.updated_at),
        "uploaded_at": _serialize_datetime(book.uploaded_at),
    }


def serialize_book_word(book_word: BookWord, word: Word) -> dict[str, Any]:
    return {
        "book_word_id": book_word.id,
        "book_id": book_word.book_id,
        "word_id": word.id,
        "word": word.word,
        "language_code": word.language_code,
        "source_text": book_word.source_text,
        "occurrence_count": book_word.occurrence_count,
        "rank_in_book": book_word.rank_in_book,
        "meaning": word.meaning or "",
        "example": word.example or "",
        "part_of_speech": word.part_of_speech or "",
        "frequency_rank": word.frequency_rank,
        "zipf_frequency": word.zipf_frequency,
        "frequency_source": word.frequency_source or "",
        "definition_source": word.definition_source or "",
    }
