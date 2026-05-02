"""
ORM models for Vocabuildary.

The dictionary itself stays global in ``words``. User-specific learning state
lives in separate tables so a large multilingual word catalog does not carry
mostly-empty progress columns for words a user has never seen.
"""

from sqlalchemy import Boolean, Column, Date, DateTime, ForeignKey, Integer, JSON, Text, func
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
    word_metadata = Column("metadata", JSON, nullable=False, default=dict, server_default="{}")
    # `sent` keeps the v1 loop-through-all-words behaviour: once every
    # row is True, the service resets them all back to False.
    sent = Column(Boolean, nullable=False, default=False, server_default="false")
    reminder_logs = relationship("ReminderLog", back_populates="word")
    user_progress = relationship("UserWordProgress", back_populates="word")
    exposures = relationship("UserWordExposure", back_populates="word")

    def __repr__(self) -> str:
        return (
            f"<Word id={self.id} language_code={self.language_code!r} "
            f"word={self.word!r} sent={self.sent}>"
        )


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
    telegram_bot_token = Column(Text, nullable=True)
    telegram_chat_id = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    last_seen_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    reminder_logs = relationship("ReminderLog", back_populates="user")
    books = relationship("Book", back_populates="user")
    learning_settings = relationship(
        "UserLearningSettings",
        back_populates="user",
        cascade="all, delete-orphan",
        uselist=False,
    )
    word_progress = relationship("UserWordProgress", back_populates="user")
    word_exposures = relationship("UserWordExposure", back_populates="user")
    learning_sessions = relationship(
        "DailyLearningSession",
        back_populates="user",
        foreign_keys="DailyLearningSession.user_id",
    )

    @property
    def telegram_configured(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id)

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

    def __repr__(self) -> str:
        return (
            f"<Book id={self.id} user_id={self.user_id} "
            f"title={self.title!r} status={self.status!r}>"
        )
