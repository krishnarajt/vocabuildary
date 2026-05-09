import os
import unittest

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("DB_SCHEMA", "")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.db.models import VocabuildaryUser
from app.services.mobile_auth_service import (
    bearer_token_from_headers,
    issue_mobile_auth_token,
    revoke_mobile_auth_token,
    user_for_mobile_auth_token,
)


class MobileAuthServiceTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:", future=True)
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine, future=True)

    def tearDown(self):
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def test_issues_and_resolves_mobile_token(self):
        db = self.Session()
        user = VocabuildaryUser(identity_key="gateway-user")
        db.add(user)
        db.commit()
        db.refresh(user)

        token = issue_mobile_auth_token(db, user, device_id="phone-1")

        self.assertTrue(token.startswith("vbt_"))
        self.assertEqual(
            bearer_token_from_headers({"Authorization": f"Bearer {token}"}),
            token,
        )
        resolved = user_for_mobile_auth_token(db, token)
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.identity_key, "gateway-user")

        self.assertTrue(revoke_mobile_auth_token(db, token))
        self.assertIsNone(user_for_mobile_auth_token(db, token))
        db.close()


if __name__ == "__main__":
    unittest.main()
