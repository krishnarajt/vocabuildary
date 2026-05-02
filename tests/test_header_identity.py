import unittest

from app.services.header_identity import (
    AuthenticationRequiredError,
    extract_gateway_identity,
)


class GatewayIdentityTests(unittest.TestCase):
    def test_extracts_gateway_user_headers(self):
        identity = extract_gateway_identity(
            {
                "X-User-Sub": "user-123",
                "X-User-Email": "alice@example.com",
                "X-User-Name": "Alice",
                "Cookie": "sid=secret",
                "Authorization": "Bearer secret",
            }
        )

        self.assertEqual(identity.identity_key, "user-123")
        self.assertEqual(identity.sub, "user-123")
        self.assertEqual(identity.email, "alice@example.com")
        self.assertEqual(identity.name, "Alice")
        self.assertEqual(
            identity.raw_headers,
            {
                "x-user-sub": "user-123",
                "x-user-email": "alice@example.com",
                "x-user-name": "Alice",
            },
        )

    def test_falls_back_to_email_when_sub_is_missing(self):
        identity = extract_gateway_identity({"X-User-Email": "alice@example.com"})

        self.assertEqual(identity.identity_key, "alice@example.com")
        self.assertIsNone(identity.sub)

    def test_rejects_requests_without_identity(self):
        with self.assertRaises(AuthenticationRequiredError):
            extract_gateway_identity({"Host": "localhost", "Cookie": "sid=secret"})


if __name__ == "__main__":
    unittest.main()
