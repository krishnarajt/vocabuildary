import os
import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("DB_SCHEMA", "")

from app.db.database import Base
from app.db.models import UserWordExposure, UserWordProgress, VocabuildaryUser, Word
from app.services.reminder_content_service import ReminderContent, RenderedReminderMessage
from app.services.word_service import (
    LearningPlanLockedError,
    build_daily_learning_plan,
    rebuild_daily_learning_plan,
    send_daily_word,
    update_daily_learning_plan,
)
from app.services.user_service import get_configured_users


class FakeTelegram:
    def __init__(self):
        self.messages = []

    def send_message(self, text, parse_mode="HTML"):
        self.messages.append((text, parse_mode))
        return {"ok": True}


class LearningScheduleTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:", future=True)
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine, future=True)

    def tearDown(self):
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def _seed_user_and_words(self):
        db = self.Session()
        user = VocabuildaryUser(
            identity_key="user-1",
            telegram_bot_token="token",
            telegram_chat_id="chat",
        )
        db.add(user)
        db.add_all(
            [
                Word(language_code="en", word="alpha", meaning="first", example="Alpha leads."),
                Word(language_code="en", word="bravo", meaning="bold", example="Bravo was bold."),
                Word(
                    language_code="en",
                    word="charlie",
                    meaning="steady",
                    example="Charlie stayed steady.",
                ),
            ]
        )
        db.commit()
        db.refresh(user)
        return db, user

    def test_send_daily_word_records_progress_and_exposure(self):
        db, user = self._seed_user_and_words()
        telegram = FakeTelegram()
        rendered = RenderedReminderMessage(
            message="lesson",
            content=ReminderContent(
                paragraph="paragraph",
                history="history",
                etymology="etymology",
                cloze_prompt="",
            ),
        )

        with patch("app.services.word_service.render_reminder_message", return_value=rendered):
            success, word = send_daily_word(db=db, telegram=telegram, user=user)

        self.assertTrue(success)
        self.assertIsNotNone(word)
        self.assertEqual(telegram.messages, [("lesson", "HTML")])
        progress = db.query(UserWordProgress).one()
        self.assertEqual(progress.word_id, word.id)
        self.assertEqual(progress.encounter_count, 1)
        self.assertGreater(progress.progress_percent, 0)
        exposure = db.query(UserWordExposure).one()
        self.assertEqual(exposure.exposure_kind, "new_word")
        db.close()

    def test_apprise_provider_is_selected_for_user_send(self):
        db, user = self._seed_user_and_words()
        user.notification_provider = "apprise"
        user.apprise_urls = "json://example.test"
        db.commit()
        notifier = FakeTelegram()
        rendered = RenderedReminderMessage(
            message="apprise lesson",
            content=ReminderContent(
                paragraph="paragraph",
                history="history",
                etymology="etymology",
                cloze_prompt="",
            ),
        )

        with patch("app.services.notification_service.AppriseAdapter", return_value=notifier):
            with patch("app.services.word_service.render_reminder_message", return_value=rendered):
                success, word = send_daily_word(db=db, user=user)

        self.assertTrue(success)
        self.assertIsNotNone(word)
        self.assertEqual(notifier.messages, [("apprise lesson", "HTML")])
        db.close()

    def test_get_configured_users_includes_selected_apprise_users(self):
        db = self.Session()
        apprise_user = VocabuildaryUser(
            identity_key="apprise-user",
            notification_provider="apprise",
            apprise_urls="json://example.test",
        )
        telegram_user = VocabuildaryUser(
            identity_key="telegram-user",
            notification_provider="telegram",
            telegram_bot_token="token",
            telegram_chat_id="chat",
        )
        incomplete_user = VocabuildaryUser(
            identity_key="incomplete-user",
            notification_provider="apprise",
        )
        db.add_all([apprise_user, telegram_user, incomplete_user])
        db.commit()

        users = get_configured_users(db)

        self.assertEqual([user.identity_key for user in users], ["apprise-user", "telegram-user"])
        db.close()

    def test_next_day_plan_uses_due_word_as_cloze_review(self):
        db, user = self._seed_user_and_words()
        day_one = date(2026, 5, 1)
        first_plan = build_daily_learning_plan(db, user, study_date=day_one)
        self.assertIsNotNone(first_plan)
        first_plan.session.sent_at = __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        )
        progress = (
            db.query(UserWordProgress)
            .filter(UserWordProgress.user_id == user.id)
            .filter(UserWordProgress.word_id == first_plan.new_word.id)
            .one()
        )
        progress.encounter_count = 1
        progress.progress_percent = 13
        progress.next_due_on = day_one + timedelta(days=1)
        progress.last_seen_on = day_one
        db.commit()

        second_plan = build_daily_learning_plan(db, user, study_date=day_one + timedelta(days=1))

        self.assertIsNotNone(second_plan)
        self.assertIsNotNone(second_plan.cloze_word)
        self.assertEqual(second_plan.cloze_word.id, first_plan.new_word.id)
        db.close()

    def test_update_learning_plan_edits_unsent_review_slots(self):
        db, user = self._seed_user_and_words()
        study_date = date(2026, 5, 2)
        words = db.query(Word).order_by(Word.word.asc()).all()
        db.add_all(
            [
                UserWordProgress(
                    user_id=user.id,
                    word_id=words[0].id,
                    encounter_count=1,
                    progress_percent=25,
                    last_seen_on=study_date - timedelta(days=1),
                    next_due_on=study_date,
                ),
                UserWordProgress(
                    user_id=user.id,
                    word_id=words[1].id,
                    encounter_count=2,
                    progress_percent=50,
                    last_seen_on=study_date - timedelta(days=1),
                    next_due_on=study_date,
                ),
            ]
        )
        db.commit()

        plan = build_daily_learning_plan(db, user, study_date=study_date)
        self.assertIsNotNone(plan)
        edited = update_daily_learning_plan(
            db,
            user,
            {
                "cloze_word_id": words[0].id,
                "context_word_ids": [words[1].id],
            },
            study_date=study_date,
        )

        self.assertIsNotNone(edited)
        self.assertEqual(edited.cloze_word.id, words[0].id)
        self.assertEqual([word.id for word in edited.context_words], [words[1].id])
        self.assertEqual(edited.session.reminder_word_ids, [words[0].id, words[1].id])
        db.close()

    def test_rebuild_learning_plan_rejects_sent_session(self):
        db, user = self._seed_user_and_words()
        study_date = date(2026, 5, 2)
        plan = build_daily_learning_plan(db, user, study_date=study_date)
        self.assertIsNotNone(plan)
        plan.session.sent_at = datetime.now(timezone.utc)
        db.commit()

        with self.assertRaises(LearningPlanLockedError):
            rebuild_daily_learning_plan(db, user, study_date=study_date)
        db.close()


if __name__ == "__main__":
    unittest.main()
