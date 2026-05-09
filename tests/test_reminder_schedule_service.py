import os
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("DB_SCHEMA", "")

from app.db.database import Base
from app.db.models import UserReminderSlot, VocabuildaryUser
from app.services.reminder_schedule_service import update_reminder_slots_for_user


class ReminderScheduleServiceTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:", future=True)
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine, future=True)

    def tearDown(self):
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def test_creates_new_slot_without_flushing_null_required_fields(self):
        db = self.Session()
        user = VocabuildaryUser(identity_key="user-1")
        db.add(user)
        db.commit()
        db.refresh(user)

        slots = update_reminder_slots_for_user(
            db,
            user,
            {
                "slots": [
                    {
                        "label": "Morning",
                        "time_of_day": "09:30",
                        "timezone": "Asia/Kolkata",
                        "enabled": True,
                    }
                ]
            },
        )

        self.assertEqual(len(slots), 1)
        self.assertEqual(slots[0].label, "Morning")
        self.assertEqual(slots[0].time_of_day, "09:30")
        self.assertEqual(slots[0].timezone, "Asia/Kolkata")
        self.assertTrue(slots[0].enabled)

        stored = db.query(UserReminderSlot).one()
        self.assertEqual(stored.time_of_day, "09:30")
        db.close()


if __name__ == "__main__":
    unittest.main()
