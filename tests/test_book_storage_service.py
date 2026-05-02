import os
import unittest

os.environ.setdefault("DATABASE_URL", "sqlite:///test.db")
os.environ.setdefault("DB_SCHEMA", "")

from app.services.book_storage_service import (
    BookStorageService,
    BookValidationError,
    build_source_object_key,
    build_word_map_object_key,
    infer_content_type,
    sanitize_filename,
    validate_book_upload_request,
)


class FakeS3Client:
    def __init__(self):
        self.calls = []

    def generate_presigned_url(self, operation, Params, ExpiresIn):
        self.calls.append((operation, Params, ExpiresIn))
        return f"https://storage.test/{operation}/{Params['Key']}"


class BookStorageServiceTests(unittest.TestCase):
    def test_builds_organized_source_and_word_map_keys(self):
        self.assertEqual(
            build_source_object_key(7, "book-uuid", "../My Book!!.PDF"),
            "users/7/books/book-uuid/source/my-book.pdf",
        )
        self.assertEqual(
            build_word_map_object_key(7, "book-uuid"),
            "users/7/books/book-uuid/processed/word-map.json",
        )

    def test_rejects_unsupported_extensions(self):
        with self.assertRaises(BookValidationError):
            validate_book_upload_request("notes.txt", 100)

    def test_sanitizes_empty_filenames(self):
        self.assertEqual(sanitize_filename("!!!.pdf"), "book")

    def test_infers_known_book_content_type(self):
        self.assertEqual(infer_content_type("novel.epub"), "application/epub+zip")
        self.assertEqual(infer_content_type("novel.pdf", "application/pdf"), "application/pdf")

    def test_generates_presigned_put_url_with_content_type(self):
        fake_client = FakeS3Client()
        service = BookStorageService(client=fake_client, bucket_name="books")

        url = service.generate_presigned_put_url(
            "users/1/books/a/source/book.pdf",
            "application/pdf",
            expiration=123,
        )

        self.assertEqual(url, "https://storage.test/put_object/users/1/books/a/source/book.pdf")
        self.assertEqual(
            fake_client.calls,
            [
                (
                    "put_object",
                    {
                        "Bucket": "books",
                        "Key": "users/1/books/a/source/book.pdf",
                        "ContentType": "application/pdf",
                    },
                    123,
                )
            ],
        )


if __name__ == "__main__":
    unittest.main()
