"""Language-level skills, placement quizzes, and recommendation bands."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.adapters.llm_gateway import LLMGatewayAdapter
from app.db.models import (
    LanguageLevelFrequencyBand,
    LanguageQuiz,
    LanguageQuizQuestion,
    UserLanguageLevel,
    VocabuildaryUser,
)
from app.services.catalog_service import ensure_language, language_name_from_code, list_languages

logger = logging.getLogger(__name__)

CEFR_LEVELS: list[dict[str, str]] = [
    {
        "code": "A1",
        "name": "Beginner",
        "description": "Can handle familiar everyday words and very simple phrases.",
    },
    {
        "code": "A2",
        "name": "Elementary",
        "description": "Can understand common expressions and direct routine tasks.",
    },
    {
        "code": "B1",
        "name": "Intermediate",
        "description": "Can follow the main points of clear everyday input.",
    },
    {
        "code": "B2",
        "name": "Upper Intermediate",
        "description": "Can understand more complex text and explain ideas clearly.",
    },
    {
        "code": "C1",
        "name": "Advanced",
        "description": "Can use language flexibly across work, study, and social contexts.",
    },
    {
        "code": "C2",
        "name": "Proficient",
        "description": "Can understand nearly everything read or heard with nuance.",
    },
]
CEFR_CODES = {level["code"] for level in CEFR_LEVELS}

DEFAULT_FREQUENCY_BANDS: dict[str, tuple[int, int]] = {
    "A1": (1, 1000),
    "A2": (1001, 2500),
    "B1": (2501, 5000),
    "B2": (5001, 9000),
    "C1": (9001, 16000),
    "C2": (16001, 30000),
}

DEFAULT_QUIZZES: dict[str, list[dict[str, Any]]] = {
    "en": [
        {
            "type": "fill_blank",
            "question": "I ___ coffee every morning.",
            "options": ["drink", "eat", "sleep", "read"],
            "answer": "drink",
        },
        {
            "type": "meaning",
            "question": "What does 'near' mean?",
            "options": ["close", "far", "loud", "late"],
            "answer": "close",
        },
        {
            "type": "fill_blank",
            "question": "She has lived here ___ 2020.",
            "options": ["since", "for", "during", "from"],
            "answer": "since",
        },
        {
            "type": "meaning",
            "question": "What does 'reluctant' mean?",
            "options": ["unwilling", "eager", "tiny", "ancient"],
            "answer": "unwilling",
        },
        {
            "type": "fill_blank",
            "question": "The report was so ___ that it covered every detail.",
            "options": ["comprehensive", "fragile", "casual", "distant"],
            "answer": "comprehensive",
        },
        {
            "type": "meaning",
            "question": "What does 'ubiquitous' mean?",
            "options": ["found everywhere", "rarely seen", "easy to break", "without color"],
            "answer": "found everywhere",
        },
    ],
    "es": [
        {
            "type": "fill_blank",
            "question": "Yo ___ agua.",
            "options": ["bebo", "duermo", "leo", "corro"],
            "answer": "bebo",
        },
        {
            "type": "meaning",
            "question": "What does 'casa' mean?",
            "options": ["house", "street", "book", "cloud"],
            "answer": "house",
        },
        {
            "type": "fill_blank",
            "question": "Ayer nosotros ___ al mercado.",
            "options": ["fuimos", "vamos", "iremos", "ir"],
            "answer": "fuimos",
        },
        {
            "type": "meaning",
            "question": "What does 'aunque' mean?",
            "options": ["although", "because", "always", "never"],
            "answer": "although",
        },
        {
            "type": "fill_blank",
            "question": "Ojala que ella ___ pronto.",
            "options": ["vuelva", "vuelve", "volvio", "volver"],
            "answer": "vuelva",
        },
        {
            "type": "meaning",
            "question": "What does 'efimero' mean?",
            "options": ["short-lived", "expensive", "silent", "heavy"],
            "answer": "short-lived",
        },
    ],
    "fr": [
        {
            "type": "fill_blank",
            "question": "Je ___ du pain.",
            "options": ["mange", "dors", "lis", "cours"],
            "answer": "mange",
        },
        {
            "type": "meaning",
            "question": "What does 'maison' mean?",
            "options": ["house", "book", "street", "sun"],
            "answer": "house",
        },
        {
            "type": "fill_blank",
            "question": "Hier, nous ___ au musee.",
            "options": ["sommes alles", "allons", "irons", "aller"],
            "answer": "sommes alles",
        },
        {
            "type": "meaning",
            "question": "What does 'pourtant' mean?",
            "options": ["however", "therefore", "always", "never"],
            "answer": "however",
        },
        {
            "type": "fill_blank",
            "question": "Il faut que tu ___ attentif.",
            "options": ["sois", "es", "etais", "etre"],
            "answer": "sois",
        },
        {
            "type": "meaning",
            "question": "What does 'ephemere' mean?",
            "options": ["short-lived", "crowded", "loud", "faithful"],
            "answer": "short-lived",
        },
    ],
    "de": [
        {
            "type": "fill_blank",
            "question": "Ich ___ Wasser.",
            "options": ["trinke", "schlafe", "lese", "laufe"],
            "answer": "trinke",
        },
        {
            "type": "meaning",
            "question": "What does 'Haus' mean?",
            "options": ["house", "book", "street", "window"],
            "answer": "house",
        },
        {
            "type": "fill_blank",
            "question": "Gestern ___ wir ins Kino gegangen.",
            "options": ["sind", "haben", "werden", "sein"],
            "answer": "sind",
        },
        {
            "type": "meaning",
            "question": "What does 'trotzdem' mean?",
            "options": ["nevertheless", "because", "always", "soon"],
            "answer": "nevertheless",
        },
        {
            "type": "fill_blank",
            "question": "Wenn ich mehr Zeit haette, ___ ich reisen.",
            "options": ["wuerde", "werde", "bin", "habe"],
            "answer": "wuerde",
        },
        {
            "type": "meaning",
            "question": "What does 'vergaenglich' mean?",
            "options": ["transient", "lawful", "bitter", "bright"],
            "answer": "transient",
        },
    ],
    "it": [
        {
            "type": "fill_blank",
            "question": "Io ___ acqua.",
            "options": ["bevo", "dormo", "leggo", "corro"],
            "answer": "bevo",
        },
        {
            "type": "meaning",
            "question": "What does 'casa' mean?",
            "options": ["house", "book", "street", "tree"],
            "answer": "house",
        },
        {
            "type": "fill_blank",
            "question": "Ieri siamo ___ al mercato.",
            "options": ["andati", "andiamo", "andremo", "andare"],
            "answer": "andati",
        },
        {
            "type": "meaning",
            "question": "What does 'tuttavia' mean?",
            "options": ["however", "therefore", "always", "never"],
            "answer": "however",
        },
        {
            "type": "fill_blank",
            "question": "Benche sia tardi, ___ a lavorare.",
            "options": ["continuiamo", "continuavamo", "continueremo", "continuare"],
            "answer": "continuiamo",
        },
        {
            "type": "meaning",
            "question": "What does 'effimero' mean?",
            "options": ["short-lived", "noisy", "expensive", "ancient"],
            "answer": "short-lived",
        },
    ],
    "pt": [
        {
            "type": "fill_blank",
            "question": "Eu ___ agua.",
            "options": ["bebo", "durmo", "leio", "corro"],
            "answer": "bebo",
        },
        {
            "type": "meaning",
            "question": "What does 'casa' mean?",
            "options": ["house", "book", "street", "tree"],
            "answer": "house",
        },
        {
            "type": "fill_blank",
            "question": "Ontem nos ___ ao mercado.",
            "options": ["fomos", "vamos", "iremos", "ir"],
            "answer": "fomos",
        },
        {
            "type": "meaning",
            "question": "What does 'embora' mean?",
            "options": ["although", "because", "always", "never"],
            "answer": "although",
        },
        {
            "type": "fill_blank",
            "question": "Espero que ela ___ cedo.",
            "options": ["chegue", "chega", "chegou", "chegar"],
            "answer": "chegue",
        },
        {
            "type": "meaning",
            "question": "What does 'efemero' mean?",
            "options": ["short-lived", "heavy", "loud", "ancient"],
            "answer": "short-lived",
        },
    ],
    "hi": [
        {
            "type": "fill_blank",
            "question": "मैं पानी ___ हूँ।",
            "options": ["पीता", "सोता", "पढ़ता", "दौड़ता"],
            "answer": "पीता",
        },
        {
            "type": "meaning",
            "question": "What does 'घर' mean?",
            "options": ["house", "book", "road", "sun"],
            "answer": "house",
        },
        {
            "type": "fill_blank",
            "question": "कल हम बाज़ार ___.",
            "options": ["गए", "जाते", "जाएँगे", "जाना"],
            "answer": "गए",
        },
        {
            "type": "meaning",
            "question": "What does 'लेकिन' mean?",
            "options": ["but", "because", "always", "never"],
            "answer": "but",
        },
        {
            "type": "fill_blank",
            "question": "अगर समय होता, तो मैं यात्रा ___.",
            "options": ["करता", "करूँगा", "करता हूँ", "करना"],
            "answer": "करता",
        },
        {
            "type": "meaning",
            "question": "What does 'क्षणिक' mean?",
            "options": ["momentary", "heavy", "expensive", "noisy"],
            "answer": "momentary",
        },
    ],
    "ja": [
        {
            "type": "fill_blank",
            "question": "私は水を ___.",
            "options": ["飲みます", "寝ます", "読みます", "走ります"],
            "answer": "飲みます",
        },
        {
            "type": "meaning",
            "question": "What does '家' mean?",
            "options": ["house", "book", "road", "sun"],
            "answer": "house",
        },
        {
            "type": "fill_blank",
            "question": "昨日、私たちは市場へ ___.",
            "options": ["行きました", "行きます", "行きましょう", "行くこと"],
            "answer": "行きました",
        },
        {
            "type": "meaning",
            "question": "What does 'しかし' mean?",
            "options": ["however", "because", "always", "never"],
            "answer": "however",
        },
        {
            "type": "fill_blank",
            "question": "時間があれば、旅行に ___.",
            "options": ["行きたいです", "行きました", "行っています", "行きません"],
            "answer": "行きたいです",
        },
        {
            "type": "meaning",
            "question": "What does '儚い' mean?",
            "options": ["fleeting", "heavy", "noisy", "expensive"],
            "answer": "fleeting",
        },
    ],
    "ko": [
        {
            "type": "fill_blank",
            "question": "저는 물을 ___.",
            "options": ["마셔요", "자요", "읽어요", "달려요"],
            "answer": "마셔요",
        },
        {
            "type": "meaning",
            "question": "What does '집' mean?",
            "options": ["house", "book", "road", "sun"],
            "answer": "house",
        },
        {
            "type": "fill_blank",
            "question": "어제 우리는 시장에 ___.",
            "options": ["갔어요", "가요", "갈 거예요", "가기"],
            "answer": "갔어요",
        },
        {
            "type": "meaning",
            "question": "What does '하지만' mean?",
            "options": ["however", "because", "always", "never"],
            "answer": "however",
        },
        {
            "type": "fill_blank",
            "question": "시간이 있으면 여행을 ___.",
            "options": ["하고 싶어요", "했어요", "합니다", "하지 않아요"],
            "answer": "하고 싶어요",
        },
        {
            "type": "meaning",
            "question": "What does '덧없는' mean?",
            "options": ["fleeting", "heavy", "noisy", "expensive"],
            "answer": "fleeting",
        },
    ],
    "zh": [
        {
            "type": "fill_blank",
            "question": "我 ___ 水。",
            "options": ["喝", "睡", "读", "跑"],
            "answer": "喝",
        },
        {
            "type": "meaning",
            "question": "What does '家' mean?",
            "options": ["home", "book", "road", "sun"],
            "answer": "home",
        },
        {
            "type": "fill_blank",
            "question": "昨天我们 ___ 市场。",
            "options": ["去了", "去", "会去", "去过"],
            "answer": "去了",
        },
        {
            "type": "meaning",
            "question": "What does '但是' mean?",
            "options": ["however", "because", "always", "never"],
            "answer": "however",
        },
        {
            "type": "fill_blank",
            "question": "如果有时间，我 ___ 去旅行。",
            "options": ["想", "已经", "正在", "不"],
            "answer": "想",
        },
        {
            "type": "meaning",
            "question": "What does '短暂' mean?",
            "options": ["brief", "heavy", "noisy", "expensive"],
            "answer": "brief",
        },
    ],
}


class LanguageSkillValidationError(ValueError):
    """Raised when a language skill request is invalid."""


class LanguageQuizNotFoundError(LookupError):
    """Raised when a quiz does not exist for a language."""


class LanguageQuizGenerationError(RuntimeError):
    """Raised when the LLM cannot produce a valid quiz."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_level_code(value: Any) -> str:
    level_code = str(value or "").strip().upper()
    if level_code not in CEFR_CODES:
        raise LanguageSkillValidationError("Level must be one of A1, A2, B1, B2, C1, or C2.")
    return level_code


def _level_from_score(score: int, total: int) -> str:
    if total <= 0:
        return "A1"
    ratio = max(0.0, min(1.0, score / total))
    if ratio <= 1 / 6:
        return "A1"
    if ratio <= 2 / 6:
        return "A2"
    if ratio <= 3 / 6:
        return "B1"
    if ratio <= 4 / 6:
        return "B2"
    if ratio <= 5 / 6:
        return "C1"
    return "C2"


def ensure_default_frequency_bands(db: Session, language_code: str) -> list[LanguageLevelFrequencyBand]:
    """Ensure the language has CEFR-to-frequency rows."""
    language = ensure_language(db, language_code)
    existing = {
        band.level_code: band
        for band in db.execute(
            select(LanguageLevelFrequencyBand).where(
                LanguageLevelFrequencyBand.language_code == language.code
            )
        ).scalars()
    }
    now = _utc_now()
    for level_code, (min_rank, max_rank) in DEFAULT_FREQUENCY_BANDS.items():
        if level_code in existing:
            continue
        band = LanguageLevelFrequencyBand(
            language_code=language.code,
            level_code=level_code,
            min_frequency_rank=min_rank,
            max_frequency_rank=max_rank,
            updated_at=now,
        )
        db.add(band)
        existing[level_code] = band
    db.flush()
    return [existing[level["code"]] for level in CEFR_LEVELS if level["code"] in existing]


def get_frequency_band_for_level(
    db: Session,
    language_code: str | None,
    level_code: str | None,
) -> LanguageLevelFrequencyBand | None:
    """Return the recommendation band for a language level, creating defaults if needed."""
    if not language_code or not level_code:
        return None
    normalized_level = str(level_code).strip().upper()
    if normalized_level not in CEFR_CODES:
        return None

    ensure_default_frequency_bands(db, language_code)
    return db.execute(
        select(LanguageLevelFrequencyBand)
        .where(LanguageLevelFrequencyBand.language_code == language_code)
        .where(LanguageLevelFrequencyBand.level_code == normalized_level)
        .limit(1)
    ).scalar_one_or_none()


def get_user_language_level(
    db: Session,
    user: VocabuildaryUser,
    language_code: str | None,
) -> UserLanguageLevel | None:
    if not language_code:
        return None
    return db.execute(
        select(UserLanguageLevel)
        .where(UserLanguageLevel.user_id == user.id)
        .where(UserLanguageLevel.language_code == language_code)
        .limit(1)
    ).scalar_one_or_none()


def _serialize_frequency_band(band: LanguageLevelFrequencyBand | None) -> dict[str, Any] | None:
    if band is None:
        return None
    return {
        "language_code": band.language_code,
        "level_code": band.level_code,
        "min_frequency_rank": band.min_frequency_rank,
        "max_frequency_rank": band.max_frequency_rank,
    }


def serialize_user_language_level(level: UserLanguageLevel | None) -> dict[str, Any] | None:
    if level is None:
        return None
    return {
        "language_code": level.language_code,
        "level_code": level.level_code,
        "source": level.source,
        "quiz_id": level.quiz_id,
        "quiz_score": level.quiz_score,
        "quiz_total": level.quiz_total,
        "assessed_at": level.assessed_at.isoformat() if level.assessed_at else None,
        "created_at": level.created_at.isoformat() if level.created_at else None,
        "updated_at": level.updated_at.isoformat() if level.updated_at else None,
    }


def _serialize_skill(language: dict[str, Any], level: UserLanguageLevel | None, db: Session) -> dict[str, Any]:
    band = None
    if level is not None:
        band = get_frequency_band_for_level(db, language["code"], level.level_code)
    quiz = _get_quiz(db, language["code"], create_default=False)
    return {
        "language": language,
        "level": serialize_user_language_level(level),
        "frequency_band": _serialize_frequency_band(band),
        "quiz_available": quiz is not None,
        "quiz_id": quiz.id if quiz else None,
        "quiz_source": quiz.source if quiz else None,
    }


def list_language_skills(db: Session, user: VocabuildaryUser) -> dict[str, Any]:
    """List all catalog languages with the user's saved level state."""
    languages = list_languages(db)
    for language in languages:
        ensure_default_frequency_bands(db, language["code"])
        _get_quiz(db, language["code"], create_default=True)
    db.commit()

    levels = {
        level.language_code: level
        for level in db.execute(
            select(UserLanguageLevel).where(UserLanguageLevel.user_id == user.id)
        ).scalars()
    }
    return {
        "levels": CEFR_LEVELS,
        "items": [_serialize_skill(language, levels.get(language["code"]), db) for language in languages],
    }


def set_user_language_level(
    db: Session,
    user: VocabuildaryUser,
    language_code: str,
    level_code: str,
    *,
    source: str = "manual",
    quiz: LanguageQuiz | None = None,
    quiz_score: int | None = None,
    quiz_total: int | None = None,
) -> UserLanguageLevel:
    """Upsert a user's language level."""
    language = ensure_language(db, language_code)
    normalized_level = _normalize_level_code(level_code)
    ensure_default_frequency_bands(db, language.code)
    now = _utc_now()
    level = get_user_language_level(db, user, language.code)
    if level is None:
        level = UserLanguageLevel(user_id=user.id, language_code=language.code)
        db.add(level)

    level.level_code = normalized_level
    level.source = source
    level.quiz_id = quiz.id if quiz else None
    level.quiz_score = quiz_score
    level.quiz_total = quiz_total
    level.assessed_at = now
    level.updated_at = now
    db.commit()
    db.refresh(level)
    return level


def serialize_language_quiz(quiz: LanguageQuiz, *, include_answers: bool = False) -> dict[str, Any]:
    questions = []
    for question in sorted(quiz.questions, key=lambda item: item.position):
        serialized = {
            "id": question.id,
            "position": question.position,
            "prompt_type": question.prompt_type,
            "question_text": question.question_text,
            "options": list(question.options or []),
            "explanation": question.explanation or "",
        }
        if include_answers:
            serialized["correct_option_index"] = question.correct_option_index
            serialized["correct_answer"] = question.correct_answer
        questions.append(serialized)

    return {
        "id": quiz.id,
        "language_code": quiz.language_code,
        "title": quiz.title,
        "source": quiz.source,
        "generated_by_model": quiz.generated_by_model,
        "question_count": len(questions),
        "questions": questions,
        "created_at": quiz.created_at.isoformat() if quiz.created_at else None,
        "updated_at": quiz.updated_at.isoformat() if quiz.updated_at else None,
    }


def _get_quiz(db: Session, language_code: str, *, create_default: bool) -> LanguageQuiz | None:
    quiz = db.execute(
        select(LanguageQuiz)
        .options(joinedload(LanguageQuiz.questions))
        .where(LanguageQuiz.language_code == language_code)
        .limit(1)
    ).unique().scalar_one_or_none()
    if quiz is not None or not create_default:
        return quiz

    defaults = DEFAULT_QUIZZES.get(language_code)
    if not defaults:
        return None

    ensure_language(db, language_code)
    quiz = LanguageQuiz(
        language_code=language_code,
        title=f"{language_name_from_code(language_code)} Placement Quiz",
        source="default",
    )
    db.add(quiz)
    db.flush()
    _replace_quiz_questions(db, quiz, defaults)
    db.flush()
    return quiz


def get_language_quiz(db: Session, language_code: str) -> LanguageQuiz:
    """Return the language quiz, creating hardcoded defaults where available."""
    quiz = _get_quiz(db, language_code, create_default=True)
    if quiz is None:
        raise LanguageQuizNotFoundError("No quiz exists for this language yet.")
    db.commit()
    return _get_quiz(db, language_code, create_default=False) or quiz


def _extract_llm_content(response: dict[str, Any]) -> str:
    content = response.get("content")
    if isinstance(content, str):
        return content.strip()
    try:
        return str(response["choices"][0]["message"]["content"]).strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise LanguageQuizGenerationError("LLM response did not contain quiz content.") from exc


def _parse_json_object(raw_content: str) -> dict[str, Any]:
    content = raw_content.strip()
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", content, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        content = fenced.group(1).strip()
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        raise LanguageQuizGenerationError("LLM returned non-JSON quiz content.") from exc
    if not isinstance(payload, dict):
        raise LanguageQuizGenerationError("LLM quiz content must be a JSON object.")
    return payload


def _coerce_question(raw_question: dict[str, Any], position: int) -> dict[str, Any]:
    prompt_type = str(
        raw_question.get("type")
        or raw_question.get("prompt_type")
        or raw_question.get("kind")
        or "meaning"
    ).strip()
    if prompt_type not in {"fill_blank", "meaning"}:
        prompt_type = "meaning"

    question_text = str(
        raw_question.get("question") or raw_question.get("question_text") or ""
    ).strip()
    options = raw_question.get("options")
    if not question_text or not isinstance(options, list) or len(options) != 4:
        raise LanguageQuizGenerationError("Each quiz question must have text and four options.")
    clean_options = [str(option).strip() for option in options]
    if any(not option for option in clean_options):
        raise LanguageQuizGenerationError("Quiz options cannot be empty.")

    raw_index = raw_question.get("correct_option_index")
    answer = str(raw_question.get("answer") or raw_question.get("correct_answer") or "").strip()
    correct_index = None
    if raw_index is not None:
        try:
            parsed_index = int(raw_index)
        except (TypeError, ValueError) as exc:
            raise LanguageQuizGenerationError("correct_option_index must be a number.") from exc
        if 0 <= parsed_index < len(clean_options):
            correct_index = parsed_index
        elif 1 <= parsed_index <= len(clean_options):
            correct_index = parsed_index - 1

    if correct_index is None and answer:
        lowered_answer = answer.casefold()
        for index, option in enumerate(clean_options):
            if option.casefold() == lowered_answer:
                correct_index = index
                break

    if correct_index is None:
        raise LanguageQuizGenerationError("Each quiz question must mark the correct answer.")

    return {
        "type": prompt_type,
        "question": question_text,
        "options": clean_options,
        "answer": clean_options[correct_index],
        "correct_option_index": correct_index,
        "explanation": str(raw_question.get("explanation") or "").strip() or None,
        "position": position,
    }


def _questions_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    questions = payload.get("questions")
    if not isinstance(questions, list):
        raise LanguageQuizGenerationError("Quiz JSON must contain a questions array.")
    coerced = [
        _coerce_question(question, index + 1)
        for index, question in enumerate(questions[:12])
        if isinstance(question, dict)
    ]
    if len(coerced) < 6:
        raise LanguageQuizGenerationError("Quiz must contain at least six valid questions.")
    return coerced


def _replace_quiz_questions(
    db: Session,
    quiz: LanguageQuiz,
    questions: list[dict[str, Any]],
) -> None:
    for question in list(quiz.questions or []):
        db.delete(question)
    db.flush()
    for index, question in enumerate(questions, start=1):
        answer = str(question.get("answer") or "").strip()
        options = [str(option).strip() for option in question.get("options") or []]
        if len(options) != 4 or answer not in options:
            raise LanguageQuizGenerationError("Default quiz question options are invalid.")
        db.add(
            LanguageQuizQuestion(
                quiz_id=quiz.id,
                position=int(question.get("position") or index),
                prompt_type=str(question.get("type") or "meaning"),
                question_text=str(question.get("question") or "").strip(),
                options=options,
                correct_option_index=options.index(answer),
                correct_answer=answer,
                explanation=str(question.get("explanation") or "").strip() or None,
            )
        )


def generate_language_quiz(
    db: Session,
    user: VocabuildaryUser,
    language_code: str,
    *,
    llm: LLMGatewayAdapter | None = None,
) -> tuple[LanguageQuiz, bool]:
    """Generate and store a placement quiz if the language has none."""
    existing = _get_quiz(db, language_code, create_default=True)
    if existing is not None:
        db.commit()
        return get_language_quiz(db, language_code), False

    language = ensure_language(db, language_code)
    llm = llm or LLMGatewayAdapter()
    try:
        response = llm.chat(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You create CEFR language placement quizzes. Return only valid JSON "
                        "with a questions array. Each question must include type "
                        "('fill_blank' or 'meaning'), question, options, answer, and explanation."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Create a six-question placement quiz for {language.name} "
                        f"({language.code}). Use one question each for A1, A2, B1, B2, C1, "
                        "and C2 difficulty, ordered from easiest to hardest. Mix fill-in-the-blank "
                        "and meaning questions. Each question needs exactly four options and one "
                        "correct answer copied exactly from the options. Keep questions concise. "
                        "Return JSON only."
                    ),
                },
            ],
            temperature=0.3,
            max_tokens=1400,
        )
    except Exception as exc:
        raise LanguageQuizGenerationError(str(exc)) from exc
    payload = _parse_json_object(_extract_llm_content(response))
    questions = _questions_from_payload(payload)

    quiz = LanguageQuiz(
        language_code=language.code,
        title=str(payload.get("title") or f"{language.name} Placement Quiz").strip(),
        source="generated",
        generated_by_model=llm.default_model,
        created_by_user_id=user.id,
    )
    db.add(quiz)
    db.flush()
    _replace_quiz_questions(db, quiz, questions)
    db.commit()
    return get_language_quiz(db, language.code), True


def _answers_by_question_id(payload: dict[str, Any]) -> dict[int, int]:
    raw_answers = payload.get("answers")
    answers: dict[int, int] = {}
    if isinstance(raw_answers, dict):
        iterable = raw_answers.items()
        for raw_question_id, raw_index in iterable:
            try:
                answers[int(raw_question_id)] = int(raw_index)
            except (TypeError, ValueError) as exc:
                raise LanguageSkillValidationError("Answers must map question ids to option indexes.") from exc
        return answers

    if isinstance(raw_answers, list):
        for item in raw_answers:
            if not isinstance(item, dict):
                raise LanguageSkillValidationError("Answers must be objects.")
            try:
                question_id = int(item.get("question_id"))
                option_index = int(item.get("selected_option_index"))
            except (TypeError, ValueError) as exc:
                raise LanguageSkillValidationError("Each answer needs a question id and option index.") from exc
            answers[question_id] = option_index
        return answers

    raise LanguageSkillValidationError("Answers must be a list or object.")


def score_language_quiz(
    db: Session,
    user: VocabuildaryUser,
    language_code: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Score a submitted quiz and persist the user's assessed CEFR level."""
    quiz = get_language_quiz(db, language_code)
    questions = sorted(quiz.questions, key=lambda item: item.position)
    answers = _answers_by_question_id(payload)
    missing_ids = [question.id for question in questions if question.id not in answers]
    if missing_ids:
        raise LanguageSkillValidationError("Answer every quiz question before scoring.")

    score = 0
    correct_question_ids: list[int] = []
    answer_results = []
    for question in questions:
        selected_index = answers[question.id]
        if selected_index < 0 or selected_index >= len(question.options or []):
            raise LanguageSkillValidationError("Selected answer index is out of range.")
        is_correct = selected_index == question.correct_option_index
        if is_correct:
            score += 1
            correct_question_ids.append(question.id)
        answer_results.append(
            {
                "question_id": question.id,
                "selected_option_index": selected_index,
                "correct": is_correct,
                "correct_option_index": question.correct_option_index,
                "correct_answer": question.correct_answer,
            }
        )

    total = len(questions)
    level_code = _level_from_score(score, total)
    saved_level = set_user_language_level(
        db,
        user,
        quiz.language_code,
        level_code,
        source="quiz",
        quiz=quiz,
        quiz_score=score,
        quiz_total=total,
    )
    band = get_frequency_band_for_level(db, quiz.language_code, saved_level.level_code)
    db.commit()
    return {
        "result": {
            "level_code": level_code,
            "score": score,
            "total": total,
            "percent": round((score / total) * 100) if total else 0,
            "correct_question_ids": correct_question_ids,
            "answers": answer_results,
        },
        "skill": {
            "language": {
                "code": quiz.language_code,
                "name": language_name_from_code(quiz.language_code),
            },
            "level": serialize_user_language_level(saved_level),
            "frequency_band": _serialize_frequency_band(band),
            "quiz_available": True,
            "quiz_id": quiz.id,
            "quiz_source": quiz.source,
        },
    }
