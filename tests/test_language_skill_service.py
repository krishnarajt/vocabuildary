import os
import unittest
from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("DB_SCHEMA", "")

from app.db.database import Base
from app.db.models import LanguageQuiz, UserLanguageLevel, VocabuildaryUser, Word
from app.services.language_skill_service import (
    generate_language_quiz,
    get_language_quiz,
    score_language_quiz,
    set_user_language_level,
)
from app.services.word_service import build_daily_learning_plan


class FakeLLM:
    default_model = "fake-model"

    def __init__(self):
        self.calls = []

    def chat(self, messages, **kwargs):
        self.calls.append({"messages": messages, "kwargs": kwargs})
        return {
            "content": """
            {
              "title": "Test Placement",
              "questions": [
                {"type":"fill_blank","question":"One ___","options":["a","b","c","d"],"answer":"a"},
                {"type":"meaning","question":"Two?","options":["a","b","c","d"],"answer":"b"},
                {"type":"fill_blank","question":"Three ___","options":["a","b","c","d"],"answer":"c"},
                {"type":"meaning","question":"Four?","options":["a","b","c","d"],"answer":"d"},
                {"type":"fill_blank","question":"Five ___","options":["a","b","c","d"],"answer":"a"},
                {"type":"meaning","question":"Six?","options":["a","b","c","d"],"answer":"b"}
              ]
            }
            """
        }


class LanguageSkillServiceTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:", future=True)
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine, future=True)

    def tearDown(self):
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def _seed_user(self):
        db = self.Session()
        user = VocabuildaryUser(identity_key="user-1")
        db.add(user)
        db.commit()
        db.refresh(user)
        return db, user

    def test_default_quiz_is_persisted_and_scored_to_cefr_level(self):
        db, user = self._seed_user()
        quiz = get_language_quiz(db, "en")

        self.assertEqual(quiz.language_code, "en")
        self.assertEqual(len(quiz.questions), 6)
        self.assertEqual(db.query(LanguageQuiz).count(), 1)

        answers = [
            {
                "question_id": question.id,
                "selected_option_index": question.correct_option_index,
            }
            for question in quiz.questions
        ]
        scored = score_language_quiz(db, user, "en", {"answers": answers})

        self.assertEqual(scored["result"]["score"], 6)
        self.assertEqual(scored["result"]["level_code"], "C2")
        saved_level = db.query(UserLanguageLevel).one()
        self.assertEqual(saved_level.level_code, "C2")
        self.assertEqual(saved_level.source, "quiz")
        db.close()

    def test_generate_quiz_skips_when_default_exists(self):
        db, user = self._seed_user()
        llm = FakeLLM()

        quiz, generated = generate_language_quiz(db, user, "en", llm=llm)

        self.assertFalse(generated)
        self.assertEqual(quiz.source, "default")
        self.assertEqual(llm.calls, [])
        db.close()

    def test_generate_quiz_stores_llm_questions_when_missing(self):
        db, user = self._seed_user()
        llm = FakeLLM()

        quiz, generated = generate_language_quiz(db, user, "eo", llm=llm)

        self.assertTrue(generated)
        self.assertEqual(quiz.language_code, "eo")
        self.assertEqual(quiz.source, "generated")
        self.assertEqual(quiz.generated_by_model, "fake-model")
        self.assertEqual(len(quiz.questions), 6)
        self.assertEqual(len(llm.calls), 1)
        db.close()

    def test_daily_plan_prefers_user_level_frequency_band(self):
        db, user = self._seed_user()
        db.add_all(
            [
                Word(
                    language_code="en",
                    word="apple",
                    meaning="fruit",
                    example="An apple fell.",
                    frequency_rank=100,
                ),
                Word(
                    language_code="en",
                    word="anomaly",
                    meaning="something unusual",
                    example="The anomaly stood out.",
                    frequency_rank=3000,
                ),
            ]
        )
        db.commit()
        set_user_language_level(db, user, "en", "B1")

        plan = build_daily_learning_plan(db, user, study_date=date(2026, 5, 2))

        self.assertIsNotNone(plan)
        self.assertEqual(plan.new_word.word, "anomaly")
        db.close()


if __name__ == "__main__":
    unittest.main()
