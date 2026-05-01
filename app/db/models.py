"""
ORM models for Vocabuildary.

v1.5 keeps the exact v1 schema (word / meaning / example / sent) so the
existing words.csv and the loop-until-all-seen logic keep working.
v2 will grow this into language, type, register, SRS state, etc.
"""

from sqlalchemy import Column, Integer, Text, Boolean
from sqlalchemy.schema import UniqueConstraint

from app.common import constants
from app.db.database import Base


class Word(Base):
    """A single vocabulary entry. One row per unique word."""

    __tablename__ = "words"
    __table_args__ = (
        UniqueConstraint("word", name="uq_words_word"),
        {"schema": constants.DB_SCHEMA} if constants.DB_SCHEMA else {},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    word = Column(Text, nullable=False)
    meaning = Column(Text, nullable=False)
    example = Column(Text, nullable=False)
    # `sent` keeps the v1 loop-through-all-words behaviour: once every
    # row is True, the service resets them all back to False.
    sent = Column(Boolean, nullable=False, default=False, server_default="false")

    def __repr__(self) -> str:
        return f"<Word id={self.id} word={self.word!r} sent={self.sent}>"
