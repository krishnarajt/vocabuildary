"""
ORM models for Vocabuildary.

The dictionary itself stays global in ``words``. User-specific learning state
lives in separate tables so a large multilingual word catalog does not carry
mostly-empty progress columns for words a user has never seen.
"""

from sqlalchemy import Boolean, Column, Date, DateTime, Float, ForeignKey, Integer, JSON, Text, func
from sqlalchemy.schema import UniqueConstraint
from sqlalchemy.orm import relationship

from app.common import constants
from app.db.database import Base


class Word(Base):
    """A single vocabulary entry. One row per unique word."""

    __tablename__ = "words"
    __table_args__ = (
        UniqueConstraint("language_code", "word", name="uq_words_language_word"),
        {"schema": constants.DB_SCHEMA} if constants.DB_SCHEMA else {},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    language_code = Column(
        Text,
        nullable=False,
        default=constants.DEFAULT_TARGET_LANGUAGE_CODE,
        server_default=constants.DEFAULT_TARGET_LANGUAGE_CODE,
    )
    word = Column(Text, nullable=False)
    meaning = Column(Text, nullable=False)
    example = Column(Text, nullable=False)
    part_of_speech = Column(Text, nullable=True)
    pronunciation = Column(Text, nullable=True)
    origin_language = Column(Text, nullable=True)
    etymology = Column(Text, nullable=True)
    register = Column(Text, nullable=True)
    difficulty_level = Column(Integer, nullable=True)
    frequency_rank = Column(Integer, nullable=True)
    frequency_score = Column(Float, nullable=True)
    zipf_frequency = Column(Float, nullable=True)
    frequency_source = Column(Text, nullable=True)
    definition_source = Column(Text, nullable=True)
    frequency_updated_at = Column(DateTime(timezone=True), nullable=True)
    definition_updated_at = Column(DateTime(timezone=True), nullable=True)
    word_metadata = Column("metadata", JSON, nullable=False, default=dict, server_default="{}")
    # `sent` keeps the v1 loop-through-all-words behaviour: once every
    # row is True, the service resets them all back to False.
    sent = Column(Boolean, nullable=False, default=False, server_default="false")
    reminder_logs = relationship("ReminderLog", back_populates="word")
    user_progress = relationship("UserWordProgress", back_populates="word")
    exposures = relationship("UserWordExposure", back_populates="word")
    book_words = relationship("BookWord", back_populates="word")

    def __repr__(self) -> str:
        return (
            f"<Word id={self.id} language_code={self.language_code!r} "
            f"word={self.word!r} sent={self.sent}>"
        )


class DictionaryImportRun(Base):
    """A UI-triggered dictionary/frequency import and its progress."""

    __tablename__ = "dictionary_import_runs"
    __table_args__ = (
        {"schema": constants.DB_SCHEMA} if constants.DB_SCHEMA else {},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    source = Column(Text, nullable=False)
    language_code = Column(
        Text,
        nullable=False,
        default=constants.DEFAULT_TARGET_LANGUAGE_CODE,
        server_default=constants.DEFAULT_TARGET_LANGUAGE_CODE,
    )
    status = Column(Text, nullable=False, default="queued", server_default="queued")
    chunk_index = Column(Integer, nullable=True)
    chunk_count = Column(Integer, nullable=True)
    total_items = Column(Integer, nullable=True)
    processed_items = Column(Integer, nullable=False, default=0, server_default="0")
    inserted_items = Column(Integer, nullable=False, default=0, server_default="0")
    updated_items = Column(Integer, nullable=False, default=0, server_default="0")
    skipped_items = Column(Integer, nullable=False, default=0, server_default="0")
    error_message = Column(Text, nullable=True)
    started_by_user_id = Column(
        Integer,
        ForeignKey(
            f"{constants.DB_SCHEMA}.vocabuildary_users.id"
            if constants.DB_SCHEMA
            else "vocabuildary_users.id"
        ),
        nullable=True,
    )
    params = Column(JSON, nullable=False, default=dict, server_default="{}")
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class Language(Base):
    """A language available in the learning catalog."""

    __tablename__ = "languages"
    __table_args__ = (
        {"schema": constants.DB_SCHEMA} if constants.DB_SCHEMA else {},
    )

    code = Column(Text, primary_key=True)
    name = Column(Text, nullable=False)
    native_name = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    quizzes = relationship("LanguageQuiz", back_populates="language")
    level_frequency_bands = relationship("LanguageLevelFrequencyBand", back_populates="language")
    user_levels = relationship("UserLanguageLevel", back_populates="language")


class LanguageLevelFrequencyBand(Base):
    """Frequency range to recommend for a CEFR language level."""

    __tablename__ = "language_level_frequency_bands"
    __table_args__ = (
        UniqueConstraint("language_code", "level_code", name="uq_level_frequency_language_level"),
        {"schema": constants.DB_SCHEMA} if constants.DB_SCHEMA else {},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    language_code = Column(
        Text,
        ForeignKey(
            f"{constants.DB_SCHEMA}.languages.code" if constants.DB_SCHEMA else "languages.code"
        ),
        nullable=False,
    )
    level_code = Column(Text, nullable=False)
    min_frequency_rank = Column(Integer, nullable=True)
    max_frequency_rank = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    language = relationship("Language", back_populates="level_frequency_bands")


class LanguageQuiz(Base):
    """One active placement quiz for a language."""

    __tablename__ = "language_quizzes"
    __table_args__ = (
        UniqueConstraint("language_code", name="uq_language_quizzes_language_code"),
        {"schema": constants.DB_SCHEMA} if constants.DB_SCHEMA else {},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    language_code = Column(
        Text,
        ForeignKey(
            f"{constants.DB_SCHEMA}.languages.code" if constants.DB_SCHEMA else "languages.code"
        ),
        nullable=False,
    )
    title = Column(Text, nullable=False)
    source = Column(Text, nullable=False, default="default", server_default="default")
    generated_by_model = Column(Text, nullable=True)
    created_by_user_id = Column(
        Integer,
        ForeignKey(
            f"{constants.DB_SCHEMA}.vocabuildary_users.id"
            if constants.DB_SCHEMA
            else "vocabuildary_users.id"
        ),
        nullable=True,
    )
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    language = relationship("Language", back_populates="quizzes")
    questions = relationship(
        "LanguageQuizQuestion",
        back_populates="quiz",
        cascade="all, delete-orphan",
        order_by="LanguageQuizQuestion.position",
    )


class LanguageQuizQuestion(Base):
    """A multiple-choice placement question."""

    __tablename__ = "language_quiz_questions"
    __table_args__ = (
        UniqueConstraint("quiz_id", "position", name="uq_language_quiz_questions_quiz_position"),
        {"schema": constants.DB_SCHEMA} if constants.DB_SCHEMA else {},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    quiz_id = Column(
        Integer,
        ForeignKey(
            f"{constants.DB_SCHEMA}.language_quizzes.id"
            if constants.DB_SCHEMA
            else "language_quizzes.id"
        ),
        nullable=False,
    )
    position = Column(Integer, nullable=False)
    prompt_type = Column(Text, nullable=False)
    question_text = Column(Text, nullable=False)
    options = Column(JSON, nullable=False, default=list, server_default="[]")
    correct_option_index = Column(Integer, nullable=False)
    correct_answer = Column(Text, nullable=False)
    explanation = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    quiz = relationship("LanguageQuiz", back_populates="questions")


class VocabuildaryUser(Base):
    """An Authentik/API-gateway user with Vocabuildary-specific settings."""

    __tablename__ = "vocabuildary_users"
    __table_args__ = (
        UniqueConstraint("identity_key", name="uq_vocabuildary_users_identity_key"),
        {"schema": constants.DB_SCHEMA} if constants.DB_SCHEMA else {},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    identity_key = Column(Text, nullable=False)
    gateway_sub = Column(Text, nullable=True)
    email = Column(Text, nullable=True)
    name = Column(Text, nullable=True)
    raw_identity_headers = Column(JSON, nullable=False, default=dict, server_default="{}")
    notification_provider = Column(
        Text,
        nullable=False,
        default="telegram",
        server_default="telegram",
    )
    telegram_bot_token = Column(Text, nullable=True)
    telegram_chat_id = Column(Text, nullable=True)
    apprise_urls = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    last_seen_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    reminder_logs = relationship("ReminderLog", back_populates="user")
    mobile_devices = relationship(
        "MobileDevice",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    mobile_notifications = relationship(
        "MobileNotification",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    books = relationship("Book", back_populates="user")
    learning_settings = relationship(
        "UserLearningSettings",
        back_populates="user",
        cascade="all, delete-orphan",
        uselist=False,
    )
    word_progress = relationship("UserWordProgress", back_populates="user")
    word_exposures = relationship("UserWordExposure", back_populates="user")
    reminder_slots = relationship("UserReminderSlot", back_populates="user")
    learning_sessions = relationship(
        "DailyLearningSession",
        back_populates="user",
        foreign_keys="DailyLearningSession.user_id",
    )
    language_levels = relationship(
        "UserLanguageLevel",
        back_populates="user",
        cascade="all, delete-orphan",
    )

    @property
    def telegram_configured(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id)

    @property
    def apprise_configured(self) -> bool:
        return bool((self.apprise_urls or "").strip())

    @property
    def notifications_configured(self) -> bool:
        return self.provider_configured or self.mobile_configured

    @property
    def provider_configured(self) -> bool:
        if (self.notification_provider or "telegram").lower() == "apprise":
            return self.apprise_configured
        return self.telegram_configured

    @property
    def mobile_configured(self) -> bool:
        return any(bool(device.enabled) for device in self.mobile_devices or [])

    def __repr__(self) -> str:
        return (
            f"<VocabuildaryUser id={self.id} identity_key={self.identity_key!r} "
            f"email={self.email!r}>"
        )


class ReminderLog(Base):
    """History of successfully sent reminder words."""

    __tablename__ = "reminder_logs"
    __table_args__ = (
        {"schema": constants.DB_SCHEMA} if constants.DB_SCHEMA else {},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        Integer,
        ForeignKey(
            f"{constants.DB_SCHEMA}.vocabuildary_users.id"
            if constants.DB_SCHEMA
            else "vocabuildary_users.id"
        ),
        nullable=True,
    )
    word_id = Column(
        Integer,
        ForeignKey(f"{constants.DB_SCHEMA}.words.id" if constants.DB_SCHEMA else "words.id"),
        nullable=False,
    )
    word_text = Column(Text, nullable=False)
    reminded_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    word = relationship("Word", back_populates="reminder_logs")
    user = relationship("VocabuildaryUser", back_populates="reminder_logs")

    def __repr__(self) -> str:
        return (
            f"<ReminderLog id={self.id} word_id={self.word_id} "
            f"word_text={self.word_text!r} reminded_at={self.reminded_at!r}>"
        )


class MobileDevice(Base):
    """A native mobile app install that can receive queued notifications."""

    __tablename__ = "mobile_devices"
    __table_args__ = (
        UniqueConstraint("user_id", "device_id", name="uq_mobile_devices_user_device"),
        {"schema": constants.DB_SCHEMA} if constants.DB_SCHEMA else {},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        Integer,
        ForeignKey(
            f"{constants.DB_SCHEMA}.vocabuildary_users.id"
            if constants.DB_SCHEMA
            else "vocabuildary_users.id"
        ),
        nullable=False,
    )
    device_id = Column(Text, nullable=False)
    platform = Column(Text, nullable=False, default="android", server_default="android")
    display_name = Column(Text, nullable=True)
    push_token = Column(Text, nullable=True)
    timezone = Column(Text, nullable=False, default=constants.TZ, server_default=constants.TZ)
    app_version = Column(Text, nullable=True)
    enabled = Column(Boolean, nullable=False, default=True, server_default="true")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    last_seen_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    user = relationship("VocabuildaryUser", back_populates="mobile_devices")
    notifications = relationship(
        "MobileNotification",
        back_populates="device",
        cascade="all, delete-orphan",
    )


class MobileNotification(Base):
    """Notification payload queued for a registered mobile device."""

    __tablename__ = "mobile_notifications"
    __table_args__ = (
        {"schema": constants.DB_SCHEMA} if constants.DB_SCHEMA else {},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        Integer,
        ForeignKey(
            f"{constants.DB_SCHEMA}.vocabuildary_users.id"
            if constants.DB_SCHEMA
            else "vocabuildary_users.id"
        ),
        nullable=False,
    )
    device_id = Column(
        Integer,
        ForeignKey(
            f"{constants.DB_SCHEMA}.mobile_devices.id"
            if constants.DB_SCHEMA
            else "mobile_devices.id"
        ),
        nullable=False,
    )
    session_id = Column(
        Integer,
        ForeignKey(
            f"{constants.DB_SCHEMA}.daily_learning_sessions.id"
            if constants.DB_SCHEMA
            else "daily_learning_sessions.id"
        ),
        nullable=True,
    )
    word_id = Column(
        Integer,
        ForeignKey(f"{constants.DB_SCHEMA}.words.id" if constants.DB_SCHEMA else "words.id"),
        nullable=True,
    )
    notification_kind = Column(Text, nullable=False, default="daily", server_default="daily")
    title = Column(Text, nullable=False)
    body = Column(Text, nullable=False)
    html_body = Column(Text, nullable=True)
    notification_metadata = Column(
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    queued_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    delivered_at = Column(DateTime(timezone=True), nullable=True)
    opened_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("VocabuildaryUser", back_populates="mobile_notifications")
    device = relationship("MobileDevice", back_populates="notifications")
    session = relationship("DailyLearningSession")
    word = relationship("Word")


class UserLearningSettings(Base):
    """Per-user knobs for the one-sided teaching cadence."""

    __tablename__ = "user_learning_settings"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_user_learning_settings_user_id"),
        {"schema": constants.DB_SCHEMA} if constants.DB_SCHEMA else {},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        Integer,
        ForeignKey(
            f"{constants.DB_SCHEMA}.vocabuildary_users.id"
            if constants.DB_SCHEMA
            else "vocabuildary_users.id"
        ),
        nullable=False,
    )
    enabled = Column(Boolean, nullable=False, default=True, server_default="true")
    target_language_code = Column(
        Text,
        nullable=False,
        default=constants.DEFAULT_TARGET_LANGUAGE_CODE,
        server_default=constants.DEFAULT_TARGET_LANGUAGE_CODE,
    )
    daily_review_words = Column(
        Integer,
        nullable=False,
        default=constants.DEFAULT_DAILY_REVIEW_WORDS,
        server_default=str(constants.DEFAULT_DAILY_REVIEW_WORDS),
    )
    daily_cloze_words = Column(
        Integer,
        nullable=False,
        default=constants.DEFAULT_DAILY_CLOZE_WORDS,
        server_default=str(constants.DEFAULT_DAILY_CLOZE_WORDS),
    )
    mastery_encounters = Column(
        Integer,
        nullable=False,
        default=constants.DEFAULT_MASTERY_ENCOUNTERS,
        server_default=str(constants.DEFAULT_MASTERY_ENCOUNTERS),
    )
    review_intervals = Column(
        JSON,
        nullable=False,
        default=lambda: list(constants.DEFAULT_REVIEW_INTERVAL_DAYS),
        server_default=str(constants.DEFAULT_REVIEW_INTERVAL_DAYS).replace(" ", ""),
    )
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    user = relationship("VocabuildaryUser", back_populates="learning_settings")


class UserLanguageLevel(Base):
    """The user's chosen or quiz-assessed level for a language."""

    __tablename__ = "user_language_levels"
    __table_args__ = (
        UniqueConstraint("user_id", "language_code", name="uq_user_language_levels_user_language"),
        {"schema": constants.DB_SCHEMA} if constants.DB_SCHEMA else {},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        Integer,
        ForeignKey(
            f"{constants.DB_SCHEMA}.vocabuildary_users.id"
            if constants.DB_SCHEMA
            else "vocabuildary_users.id"
        ),
        nullable=False,
    )
    language_code = Column(
        Text,
        ForeignKey(
            f"{constants.DB_SCHEMA}.languages.code" if constants.DB_SCHEMA else "languages.code"
        ),
        nullable=False,
    )
    level_code = Column(Text, nullable=False)
    source = Column(Text, nullable=False, default="manual", server_default="manual")
    quiz_id = Column(
        Integer,
        ForeignKey(
            f"{constants.DB_SCHEMA}.language_quizzes.id"
            if constants.DB_SCHEMA
            else "language_quizzes.id"
        ),
        nullable=True,
    )
    quiz_score = Column(Integer, nullable=True)
    quiz_total = Column(Integer, nullable=True)
    assessed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    user = relationship("VocabuildaryUser", back_populates="language_levels")
    language = relationship("Language", back_populates="user_levels")
    quiz = relationship("LanguageQuiz")


class UserWordProgress(Base):
    """A user's current learning state for a word they have encountered."""

    __tablename__ = "user_word_progress"
    __table_args__ = (
        UniqueConstraint("user_id", "word_id", name="uq_user_word_progress_user_word"),
        {"schema": constants.DB_SCHEMA} if constants.DB_SCHEMA else {},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        Integer,
        ForeignKey(
            f"{constants.DB_SCHEMA}.vocabuildary_users.id"
            if constants.DB_SCHEMA
            else "vocabuildary_users.id"
        ),
        nullable=False,
    )
    word_id = Column(
        Integer,
        ForeignKey(f"{constants.DB_SCHEMA}.words.id" if constants.DB_SCHEMA else "words.id"),
        nullable=False,
    )
    status = Column(Text, nullable=False, default="learning", server_default="learning")
    introduced_on = Column(Date, nullable=True)
    first_seen_at = Column(DateTime(timezone=True), nullable=True)
    last_seen_on = Column(Date, nullable=True)
    last_seen_at = Column(DateTime(timezone=True), nullable=True)
    next_due_on = Column(Date, nullable=True)
    encounter_count = Column(Integer, nullable=False, default=0, server_default="0")
    context_encounter_count = Column(Integer, nullable=False, default=0, server_default="0")
    cloze_prompt_count = Column(Integer, nullable=False, default=0, server_default="0")
    cloze_answer_count = Column(Integer, nullable=False, default=0, server_default="0")
    schedule_step = Column(Integer, nullable=False, default=0, server_default="0")
    interval_days = Column(Integer, nullable=False, default=0, server_default="0")
    progress_percent = Column(Integer, nullable=False, default=0, server_default="0")
    mastered_at = Column(DateTime(timezone=True), nullable=True)
    reset_count = Column(Integer, nullable=False, default=0, server_default="0")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    user = relationship("VocabuildaryUser", back_populates="word_progress")
    word = relationship("Word", back_populates="user_progress")
    exposures = relationship("UserWordExposure", back_populates="progress")


class DailyLearningSession(Base):
    """One generated daily teaching plan/message for one user."""

    __tablename__ = "daily_learning_sessions"
    __table_args__ = (
        UniqueConstraint("user_id", "session_date", name="uq_daily_learning_sessions_user_date"),
        {"schema": constants.DB_SCHEMA} if constants.DB_SCHEMA else {},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        Integer,
        ForeignKey(
            f"{constants.DB_SCHEMA}.vocabuildary_users.id"
            if constants.DB_SCHEMA
            else "vocabuildary_users.id"
        ),
        nullable=False,
    )
    session_date = Column(Date, nullable=False)
    new_word_id = Column(
        Integer,
        ForeignKey(f"{constants.DB_SCHEMA}.words.id" if constants.DB_SCHEMA else "words.id"),
        nullable=False,
    )
    cloze_word_id = Column(
        Integer,
        ForeignKey(f"{constants.DB_SCHEMA}.words.id" if constants.DB_SCHEMA else "words.id"),
        nullable=True,
    )
    previous_cloze_session_id = Column(
        Integer,
        ForeignKey(
            f"{constants.DB_SCHEMA}.daily_learning_sessions.id"
            if constants.DB_SCHEMA
            else "daily_learning_sessions.id"
        ),
        nullable=True,
    )
    previous_cloze_word_id = Column(
        Integer,
        ForeignKey(f"{constants.DB_SCHEMA}.words.id" if constants.DB_SCHEMA else "words.id"),
        nullable=True,
    )
    reminder_word_ids = Column(JSON, nullable=False, default=list, server_default="[]")
    context_word_ids = Column(JSON, nullable=False, default=list, server_default="[]")
    generated_content = Column(JSON, nullable=False, default=dict, server_default="{}")
    cloze_prompt = Column(Text, nullable=True)
    cloze_answer = Column(Text, nullable=True)
    message_text = Column(Text, nullable=True)
    sent_at = Column(DateTime(timezone=True), nullable=True)
    cloze_answer_revealed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    user = relationship(
        "VocabuildaryUser",
        back_populates="learning_sessions",
        foreign_keys=[user_id],
    )
    new_word = relationship("Word", foreign_keys=[new_word_id])
    cloze_word = relationship("Word", foreign_keys=[cloze_word_id])
    previous_cloze_word = relationship("Word", foreign_keys=[previous_cloze_word_id])
    previous_cloze_session = relationship("DailyLearningSession", remote_side=[id])
    exposures = relationship("UserWordExposure", back_populates="session")


class UserWordExposure(Base):
    """A concrete encounter with a word inside a daily message."""

    __tablename__ = "user_word_exposures"
    __table_args__ = (
        {"schema": constants.DB_SCHEMA} if constants.DB_SCHEMA else {},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        Integer,
        ForeignKey(
            f"{constants.DB_SCHEMA}.vocabuildary_users.id"
            if constants.DB_SCHEMA
            else "vocabuildary_users.id"
        ),
        nullable=False,
    )
    word_id = Column(
        Integer,
        ForeignKey(f"{constants.DB_SCHEMA}.words.id" if constants.DB_SCHEMA else "words.id"),
        nullable=False,
    )
    progress_id = Column(
        Integer,
        ForeignKey(
            f"{constants.DB_SCHEMA}.user_word_progress.id"
            if constants.DB_SCHEMA
            else "user_word_progress.id"
        ),
        nullable=False,
    )
    session_id = Column(
        Integer,
        ForeignKey(
            f"{constants.DB_SCHEMA}.daily_learning_sessions.id"
            if constants.DB_SCHEMA
            else "daily_learning_sessions.id"
        ),
        nullable=False,
    )
    exposure_date = Column(Date, nullable=False)
    exposure_kind = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    user = relationship("VocabuildaryUser", back_populates="word_exposures")
    word = relationship("Word", back_populates="exposures")
    progress = relationship("UserWordProgress", back_populates="exposures")
    session = relationship("DailyLearningSession", back_populates="exposures")


class UserReminderSlot(Base):
    """A user-configured time of day for notification reminders."""

    __tablename__ = "user_reminder_slots"
    __table_args__ = (
        UniqueConstraint("user_id", "time_of_day", name="uq_user_reminder_slots_user_time"),
        {"schema": constants.DB_SCHEMA} if constants.DB_SCHEMA else {},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        Integer,
        ForeignKey(
            f"{constants.DB_SCHEMA}.vocabuildary_users.id"
            if constants.DB_SCHEMA
            else "vocabuildary_users.id"
        ),
        nullable=False,
    )
    label = Column(Text, nullable=True)
    time_of_day = Column(Text, nullable=False)
    timezone = Column(Text, nullable=False, default=constants.TZ, server_default=constants.TZ)
    enabled = Column(Boolean, nullable=False, default=True, server_default="true")
    last_sent_on = Column(Date, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    user = relationship("VocabuildaryUser", back_populates="reminder_slots")


class Book(Base):
    """A user-uploaded source book and its processed word-count artifact."""

    __tablename__ = "books"
    __table_args__ = (
        UniqueConstraint("book_uuid", name="uq_books_book_uuid"),
        {"schema": constants.DB_SCHEMA} if constants.DB_SCHEMA else {},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    book_uuid = Column(Text, nullable=False)
    user_id = Column(
        Integer,
        ForeignKey(
            f"{constants.DB_SCHEMA}.vocabuildary_users.id"
            if constants.DB_SCHEMA
            else "vocabuildary_users.id"
        ),
        nullable=False,
    )

    title = Column(Text, nullable=True)
    isbn = Column(Text, nullable=True)
    author = Column(Text, nullable=True)
    language = Column(Text, nullable=True)
    language_code = Column(
        Text,
        nullable=False,
        default=constants.DEFAULT_TARGET_LANGUAGE_CODE,
        server_default=constants.DEFAULT_TARGET_LANGUAGE_CODE,
    )
    notes = Column(Text, nullable=True)

    original_filename = Column(Text, nullable=False)
    file_extension = Column(Text, nullable=False)
    mime_type = Column(Text, nullable=True)
    file_size = Column(Integer, nullable=True)

    source_bucket = Column(Text, nullable=False)
    source_object_key = Column(Text, nullable=False)
    word_map_bucket = Column(Text, nullable=True)
    word_map_object_key = Column(Text, nullable=True)

    status = Column(Text, nullable=False, default="upload_pending", server_default="upload_pending")
    learning_enabled = Column(Boolean, nullable=False, default=False, server_default="false")
    processing_error = Column(Text, nullable=True)
    total_words = Column(Integer, nullable=True)
    unique_words = Column(Integer, nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    uploaded_at = Column(DateTime(timezone=True), nullable=True)
    processed_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("VocabuildaryUser", back_populates="books")
    book_words = relationship("BookWord", back_populates="book")

    def __repr__(self) -> str:
        return (
            f"<Book id={self.id} user_id={self.user_id} "
            f"title={self.title!r} status={self.status!r}>"
        )


class BookWord(Base):
    """A canonical word occurrence summary for one processed book."""

    __tablename__ = "book_words"
    __table_args__ = (
        UniqueConstraint("book_id", "word_id", name="uq_book_words_book_word"),
        {"schema": constants.DB_SCHEMA} if constants.DB_SCHEMA else {},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    book_id = Column(
        Integer,
        ForeignKey(f"{constants.DB_SCHEMA}.books.id" if constants.DB_SCHEMA else "books.id"),
        nullable=False,
    )
    word_id = Column(
        Integer,
        ForeignKey(f"{constants.DB_SCHEMA}.words.id" if constants.DB_SCHEMA else "words.id"),
        nullable=False,
    )
    user_id = Column(
        Integer,
        ForeignKey(
            f"{constants.DB_SCHEMA}.vocabuildary_users.id"
            if constants.DB_SCHEMA
            else "vocabuildary_users.id"
        ),
        nullable=False,
    )
    language_code = Column(
        Text,
        nullable=False,
        default=constants.DEFAULT_TARGET_LANGUAGE_CODE,
        server_default=constants.DEFAULT_TARGET_LANGUAGE_CODE,
    )
    source_text = Column(Text, nullable=False)
    occurrence_count = Column(Integer, nullable=False, default=0, server_default="0")
    rank_in_book = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    book = relationship("Book", back_populates="book_words")
    word = relationship("Word", back_populates="book_words")
