"""Business logic for book uploads, processing, and public API payloads."""

from __future__ import annotations

import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common import constants
from app.db.models import Book, VocabuildaryUser
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
        notes=_clean_optional_text(payload.get("notes")),
        original_filename=filename,
        file_extension=extension,
        mime_type=content_type,
        file_size=file_size_int,
        source_bucket=storage.bucket_name,
        source_object_key=source_object_key,
        status=BOOK_STATUS_UPLOAD_PENDING,
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
        "notes": book.notes or "",
        "status": book.status,
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
