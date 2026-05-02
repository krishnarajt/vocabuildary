import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite:///test.db")
os.environ.setdefault("DB_SCHEMA", "")

from app.services.book_text_extraction import (
    BookTextExtractionError,
    count_words,
    extract_text_from_book,
    extract_text_from_html,
)


class BookTextExtractionTests(unittest.TestCase):
    def test_count_words_normalizes_case_and_apostrophes(self):
        self.assertEqual(
            count_words("Hello hello HELLO don't Don\u2019t cafe cafe."),
            {"hello": 3, "don't": 2, "cafe": 2},
        )

    def test_extract_text_from_html_strips_markup(self):
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "book.html"
            path.write_text("<h1>Title</h1><p>Alpha beta.</p>", encoding="utf-8")

            self.assertEqual(extract_text_from_html(path).strip(), "Title Alpha beta.")

    def test_extract_text_from_book_rejects_unknown_extension(self):
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "book.txt"
            path.write_text("alpha", encoding="utf-8")

            with self.assertRaises(BookTextExtractionError):
                extract_text_from_book(path)


if __name__ == "__main__":
    unittest.main()
