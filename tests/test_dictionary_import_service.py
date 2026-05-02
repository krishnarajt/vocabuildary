import os
import unittest

os.environ.setdefault("DATABASE_URL", "sqlite:///test.db")
os.environ.setdefault("DB_SCHEMA", "")

from app.services.dictionary_import_service import _normalize_word_upsert_row


class DictionaryImportServiceTests(unittest.TestCase):
    def test_normalize_word_upsert_row_maps_metadata_to_word_metadata(self):
        row = {
            "language_code": "en",
            "word": "alpha",
            "metadata": {"frequency": {"source": "wordfreq"}},
            "sent": False,
        }

        normalized = _normalize_word_upsert_row(row)

        self.assertNotIn("metadata", normalized)
        self.assertEqual(normalized["word_metadata"], {"frequency": {"source": "wordfreq"}})
        self.assertEqual(row["metadata"], {"frequency": {"source": "wordfreq"}})

    def test_normalize_word_upsert_row_leaves_existing_word_metadata_unchanged(self):
        row = {
            "language_code": "en",
            "word": "alpha",
            "word_metadata": {"definition": {"source": "kaikki"}},
            "sent": False,
        }

        normalized = _normalize_word_upsert_row(row)

        self.assertIs(normalized, row)


if __name__ == "__main__":
    unittest.main()
