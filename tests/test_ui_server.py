import os
import unittest
from io import BytesIO
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("DB_SCHEMA", "")

from app.adapters.telegram import NotificationDeliveryError
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

    def test_write_response_swallows_client_disconnect(self):
        handler = _UIRequestHandler.__new__(_UIRequestHandler)
        handler.command = "POST"
        handler.path = "/test-trigger"
        handler.close_connection = False
        handler.wfile = _BrokenWriter()
        handler.send_response = lambda status: None
        handler.send_header = lambda key, value: None
        handler._send_cors_headers = lambda: None
        handler.end_headers = lambda: None

        handler._write_response(
            status=200,
            body=b'{"ok": true}',
            content_type="application/json; charset=utf-8",
        )

        self.assertTrue(handler.close_connection)

    def test_test_trigger_returns_bad_gateway_for_notification_delivery_error(self):
        handler = _UIRequestHandler.__new__(_UIRequestHandler)
        handler.path = "/test-trigger"
        responses = []

        class _DbContext:
            def __enter__(self):
                return object()

            def __exit__(self, exc_type, exc, tb):
                return False

        handler._db_session = lambda: _DbContext()
        handler._current_user = lambda db: type(
            "User",
            (),
            {
                "id": 7,
                "notification_provider": "telegram",
                "notifications_configured": True,
            },
        )()
        handler._send_json = lambda payload, status=200: responses.append((status, payload))

        with patch(
            "app.ui.server.send_test_notification",
            side_effect=NotificationDeliveryError("Telegram delivery failed due to an upstream network error."),
        ):
            handler._handle_test_trigger()

        self.assertEqual(len(responses), 1)
        self.assertEqual(responses[0][0], 502)
        self.assertEqual(
            responses[0][1],
            {"error": "Telegram delivery failed due to an upstream network error."},
        )


class _BrokenWriter(BytesIO):
    def write(self, data):  # type: ignore[override]
        raise BrokenPipeError(32, "Broken pipe")


if __name__ == "__main__":
    unittest.main()
