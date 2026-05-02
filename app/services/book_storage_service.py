"""S3-compatible storage helpers for uploaded books and derived artifacts."""

from __future__ import annotations

import io
import json
import logging
import mimetypes
import re
from pathlib import Path
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.common import constants

logger = logging.getLogger(__name__)

ALLOWED_BOOK_EXTENSIONS = {"pdf", "epub", "mobi"}
BOOK_CONTENT_TYPES = {
    "pdf": "application/pdf",
    "epub": "application/epub+zip",
    "mobi": "application/x-mobipocket-ebook",
}


class BookStorageError(RuntimeError):
    """Raised when object storage cannot complete the requested operation."""


class BookValidationError(ValueError):
    """Raised when a requested book upload is not acceptable."""


def get_file_extension(filename: str) -> str:
    """Return a lower-case extension without the leading dot."""
    return Path(filename or "").suffix.lower().lstrip(".")


def sanitize_filename(filename: str) -> str:
    """Keep object keys readable without trusting user-supplied path pieces."""
    stem = Path(filename or "book").stem.lower()
    stem = re.sub(r"[^a-z0-9]+", "-", stem).strip("-")
    return stem[:80] or "book"


def infer_content_type(filename: str, provided: str | None = None) -> str:
    """Prefer browser-provided MIME type, then a known book mapping."""
    if provided and provided != "application/octet-stream":
        return provided

    extension = get_file_extension(filename)
    if extension in BOOK_CONTENT_TYPES:
        return BOOK_CONTENT_TYPES[extension]

    guessed, _ = mimetypes.guess_type(filename)
    return guessed or "application/octet-stream"


def validate_book_upload_request(filename: str, file_size: int | None = None) -> str:
    """Validate a source document and return its normalized extension."""
    if not filename:
        raise BookValidationError("A source document filename is required.")

    extension = get_file_extension(filename)
    if extension not in ALLOWED_BOOK_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_BOOK_EXTENSIONS))
        raise BookValidationError(f"Unsupported book format. Allowed formats: {allowed}.")

    if file_size is not None:
        if file_size <= 0:
            raise BookValidationError("The source document cannot be empty.")
        if file_size > constants.MAX_BOOK_UPLOAD_BYTES:
            max_mb = constants.MAX_BOOK_UPLOAD_BYTES / (1024 * 1024)
            raise BookValidationError(f"The source document is too large. Max size: {max_mb:.0f}MB.")

    return extension


def build_source_object_key(user_id: int, book_uuid: str, filename: str) -> str:
    extension = validate_book_upload_request(filename)
    safe_name = sanitize_filename(filename)
    return f"users/{user_id}/books/{book_uuid}/source/{safe_name}.{extension}"


def build_word_map_object_key(user_id: int, book_uuid: str) -> str:
    return f"users/{user_id}/books/{book_uuid}/processed/word-map.json"


def s3_uri(bucket: str | None, object_key: str | None) -> str | None:
    if not bucket or not object_key:
        return None
    return f"s3://{bucket}/{object_key}"


class BookStorageService:
    """Lazy S3 client wrapper shaped like the Clockwork MinIO service."""

    def __init__(self, client: Any | None = None, bucket_name: str | None = None) -> None:
        self.endpoint_url = constants.MINIO_ENDPOINT
        self.access_key = constants.MINIO_ACCESS_KEY
        self.secret_key = constants.MINIO_SECRET_KEY
        self.region = constants.MINIO_REGION
        self.bucket_name = bucket_name or constants.MINIO_BUCKET
        self._client = client
        self._initialized = client is not None

    @property
    def client(self):
        if self._client is None:
            self._client = boto3.client(
                "s3",
                endpoint_url=self.endpoint_url,
                aws_access_key_id=self.access_key,
                aws_secret_access_key=self.secret_key,
                region_name=self.region,
                config=Config(signature_version="s3v4"),
            )
        if not self._initialized:
            self._ensure_bucket_exists()
            self._initialized = True
        return self._client

    def _ensure_bucket_exists(self) -> None:
        try:
            self._client.head_bucket(Bucket=self.bucket_name)
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code", "")
            if error_code in ("404", "NoSuchBucket"):
                try:
                    self._client.create_bucket(Bucket=self.bucket_name)
                    logger.info("Created book storage bucket: %s", self.bucket_name)
                except ClientError as create_exc:
                    logger.warning("Could not create book storage bucket: %s", create_exc)
            else:
                logger.warning("Could not verify book storage bucket: %s", exc)
        except Exception as exc:
            logger.warning("Book storage is not reachable during bucket check: %s", exc)

    def generate_presigned_put_url(
        self,
        object_key: str,
        content_type: str,
        expiration: int = constants.BOOK_UPLOAD_URL_EXPIRATION_SECONDS,
    ) -> str:
        try:
            return self.client.generate_presigned_url(
                "put_object",
                Params={
                    "Bucket": self.bucket_name,
                    "Key": object_key,
                    "ContentType": content_type,
                },
                ExpiresIn=expiration,
            )
        except ClientError as exc:
            raise BookStorageError("Failed to generate upload URL.") from exc

    def generate_presigned_get_url(
        self,
        object_key: str,
        expiration: int = constants.BOOK_DOWNLOAD_URL_EXPIRATION_SECONDS,
    ) -> str:
        try:
            return self.client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket_name, "Key": object_key},
                ExpiresIn=expiration,
            )
        except ClientError as exc:
            raise BookStorageError("Failed to generate download URL.") from exc

    def download_object_to_file(self, object_key: str, destination: Path) -> None:
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            self.client.download_file(self.bucket_name, object_key, str(destination))
        except ClientError as exc:
            raise BookStorageError("Failed to download source book.") from exc

    def upload_json(self, object_key: str, payload: dict[str, int]) -> None:
        body = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        try:
            self.client.put_object(
                Bucket=self.bucket_name,
                Key=object_key,
                Body=io.BytesIO(body.encode("utf-8")),
                ContentType="application/json",
            )
        except ClientError as exc:
            raise BookStorageError("Failed to upload processed word map.") from exc


_book_storage_service: BookStorageService | None = None


def get_book_storage_service() -> BookStorageService:
    global _book_storage_service
    if _book_storage_service is None:
        _book_storage_service = BookStorageService()
    return _book_storage_service
