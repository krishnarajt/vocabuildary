import os
import unittest

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("DB_SCHEMA", "")

from app.ui.server import _UIRequestHandler


class UIServicePathTests(unittest.TestCase):
    def test_normalizes_gateway_service_prefix(self):
        self.assertEqual(_UIRequestHandler._service_path("/api/vocabuildary"), "/")
        self.assertEqual(_UIRequestHandler._service_path("/api/vocabuildary/"), "/")
        self.assertEqual(_UIRequestHandler._service_path("/api/vocabuildary/me"), "/me")
        self.assertEqual(
            _UIRequestHandler._service_path("/api/vocabuildary/books/12/words"),
            "/books/12/words",
        )

    def test_keeps_direct_api_prefix_compatibility(self):
        self.assertEqual(_UIRequestHandler._service_path("/api"), "/")
        self.assertEqual(_UIRequestHandler._service_path("/api/me"), "/me")
        self.assertEqual(_UIRequestHandler._service_path("/health"), "/health")

    def test_mobile_redirect_preserves_existing_query(self):
        redirected = _UIRequestHandler._mobile_redirect_with_token(
            "com.kptgames.vocabuildary://auth?state=abc",
            "vbt_secret",
        )

        self.assertEqual(
            redirected,
            "com.kptgames.vocabuildary://auth?state=abc&token=vbt_secret&token_type=Bearer",
        )


if __name__ == "__main__":
    unittest.main()
