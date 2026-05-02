import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "sqlite:///test.db")
os.environ.setdefault("DB_SCHEMA", "")

from app.services.book_service import create_book_upload, serialize_book


class FakeStorage:
    bucket_name = "vocabuildary-books"

    def __init__(self):
        self.put_requests = []

    def generate_presigned_put_url(self, object_key, content_type):
        self.put_requests.append((object_key, content_type))
        return f"https://storage.test/{object_key}"


class FakeDB:
    def __init__(self):
        self.added = None
        self.commits = 0

    def add(self, item):
        self.added = item
        item.id = 42

    def commit(self):
        self.commits += 1

    def refresh(self, item):
        return item


class BookServiceTests(unittest.TestCase):
    def test_create_book_upload_persists_pending_book_and_returns_put_target(self):
        db = FakeDB()
        storage = FakeStorage()
        user = SimpleNamespace(id=9)

        book, upload = create_book_upload(
            db,
            user,
            {
                "title": "My Book",
                "isbn": "123",
                "filename": "My Book.pdf",
                "content_type": "application/pdf",
                "file_size": 2048,
            },
            storage=storage,
        )

        self.assertEqual(book.id, 42)
        self.assertEqual(book.user_id, 9)
        self.assertEqual(book.title, "My Book")
        self.assertEqual(book.status, "upload_pending")
        self.assertEqual(book.source_bucket, "vocabuildary-books")
        self.assertEqual(upload["method"], "PUT")
        self.assertEqual(upload["headers"], {"Content-Type": "application/pdf"})
        self.assertEqual(db.commits, 1)
        self.assertEqual(storage.put_requests[0][1], "application/pdf")
        self.assertTrue(storage.put_requests[0][0].startswith("users/9/books/"))

    def test_serialize_book_includes_source_and_processed_links(self):
        book = SimpleNamespace(
            id=1,
            book_uuid="uuid",
            title="Title",
            isbn="",
            author="",
            language="",
            notes="",
            status="processed",
            processing_error=None,
            original_filename="book.pdf",
            file_extension="pdf",
            mime_type="application/pdf",
            file_size=99,
            source_bucket="bucket",
            source_object_key="users/1/books/uuid/source/book.pdf",
            word_map_bucket="bucket",
            word_map_object_key="users/1/books/uuid/processed/word-map.json",
            total_words=10,
            unique_words=4,
            created_at=None,
            updated_at=None,
            uploaded_at=None,
            processed_at=None,
        )

        payload = serialize_book(book)

        self.assertEqual(payload["name"], "Title")
        self.assertEqual(payload["source"]["s3_uri"], "s3://bucket/users/1/books/uuid/source/book.pdf")
        self.assertEqual(
            payload["processed"]["s3_uri"],
            "s3://bucket/users/1/books/uuid/processed/word-map.json",
        )


if __name__ == "__main__":
    unittest.main()
