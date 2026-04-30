# modules/ielts_reading/models.py
# SQLAlchemy ORM modellari — IELTS Reading

from __future__ import annotations

from datetime import datetime, timezone
import enum
import random
import string

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    func,
)
from sqlalchemy.orm import relationship

from app.core.database import Base, UUIDType


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class UserRoleEnum(str, enum.Enum):
    ADMIN = "ADMIN"
    TEACHER = "TEACHER"
    USER = "USER"


class SubscriptionTierEnum(str, enum.Enum):
    """
    Foydalanuvchi obuna darajasi.
    FREE    — cheklangan testlar (faqat is_free=True testlar)
    PREMIUM — barcha testlar + part-level attempt
    PRO     — PREMIUM + EXAM mode + cheksiz tarix
    """

    FREE = "FREE"
    PREMIUM = "PREMIUM"
    PRO = "PRO"


class DifficultyEnum(str, enum.Enum):
    EASY = "EASY"
    MEDIUM = "MEDIUM"
    HARD = "HARD"


class QuestionTypeEnum(str, enum.Enum):
    MATCHING_INFORMATION = "MATCHING_INFORMATION"
    MATCHING_HEADINGS = "MATCHING_HEADINGS"
    MATCHING_NAMES = "MATCHING_NAMES"  # ← yangi
    MATCHING_SENTENCE_ENDINGS = "MATCHING_SENTENCE_ENDINGS"  # ← yangi
    SUMMARY_COMPLETION = "SUMMARY_COMPLETION"
    SUMMARY_COMPLETION_DRAG_DROP = "SUMMARY_COMPLETION_DRAG_DROP"
    SENTENCE_COMPLETION = "SENTENCE_COMPLETION"
    MULTIPLE_CHOICE = "MULTIPLE_CHOICE"
    TRUE_FALSE_NOT_GIVEN = "TRUE_FALSE_NOT_GIVEN"
    YES_NO_NOT_GIVEN = "YES_NO_NOT_GIVEN"


class AnswerStatusEnum(str, enum.Enum):
    CORRECT = "CORRECT"
    INCORRECT = "INCORRECT"
    UNANSWERED = "UNANSWERED"


class AttemptModeEnum(str, enum.Enum):
    PRACTICE = "PRACTICE"  # Cheksiz urinish, javoblar darhol ko'rinadi (FREE+)
    EXAM = "EXAM"  # Faqat 1 marta, haqiqiy IELTS sharoiti (PRO only)


class AttemptScopeEnum(str, enum.Enum):
    """
    Attempt qamrovi.
    FULL — butun test (3 ta part) — barcha darajalar uchun mavjud
    PART — faqat bitta passage    — PREMIUM va PRO uchun mavjud
    """

    FULL = "FULL"
    PART = "PART"


# ---------------------------------------------------------------------------
# ReadingTest
# ---------------------------------------------------------------------------


def _gen_id() -> str:
    chars = string.ascii_uppercase + string.digits  # A-Z + 0-9
    return "".join(random.choices(chars, k=8))


class ReadingTest(Base):
    """Bitta to'liq IELTS Reading testi. Misol: 'Cambridge 7_Test 1'"""

    __tablename__ = "reading_tests"

    id = Column(String(8), primary_key=True, default=_gen_id, index=True)
    global_title = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True)

    # Obuna cheklovlari
    # is_free=True  → FREE foydalanuvchilar ham ko'ra oladi
    # is_free=False → faqat PREMIUM / PRO foydalanuvchilar
    is_free = Column(Boolean, default=False)

    # Testning asosiy question type lari (filtrlash uchun)
    # Misol: ["MULTIPLE_CHOICE", "TRUE_FALSE_NOT_GIVEN"]
    question_types = Column(JSON, nullable=True, default=list)

    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at = Column(
        DateTime,
        default=datetime.now(timezone.utc),
        onupdate=datetime.now(timezone.utc),
        nullable=True,
    )

    parts = relationship(
        "ReadingPart",
        back_populates="test",
        cascade="all, delete-orphan",
        order_by="ReadingPart.part",
        lazy="selectin",
    )
    attempts = relationship(
        "UserTestAttempt",
        back_populates="test",
        cascade="all, delete-orphan",
    )


# ---------------------------------------------------------------------------
# ReadingPart
# ---------------------------------------------------------------------------


class ReadingPart(Base):
    """Testning bir qismi — bitta passage + savol guruhlari."""

    __tablename__ = "reading_parts"

    id = Column(Integer, primary_key=True, index=True)
    test_id = Column(
        String(8),  # ✅ TO'G'RI
        ForeignKey("reading_tests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    part = Column(Integer, nullable=False)  # 1 | 2 | 3
    title = Column(String(255), nullable=False)
    content = Column(Text, nullable=False)  # passage matni
    time_limit_minutes = Column(Integer, default=20, nullable=False)
    difficulty = Column(
        SAEnum(DifficultyEnum), default=DifficultyEnum.MEDIUM, nullable=False
    )
    is_active = Column(Boolean, default=True, nullable=False)
    total_questions = Column(Integer, default=0, nullable=False)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    test = relationship("ReadingTest", back_populates="parts")
    question_groups = relationship(
        "QuestionGroup",
        back_populates="part",
        cascade="all, delete-orphan",
        order_by="QuestionGroup.question_number",
        lazy="selectin",
    )


# ---------------------------------------------------------------------------
# QuestionGroup
# ---------------------------------------------------------------------------


class QuestionGroup(Base):
    """Bir xil instruction va type ostidagi savollar guruhi."""

    __tablename__ = "question_groups"

    id = Column(Integer, primary_key=True, index=True)
    part_id = Column(
        Integer,
        ForeignKey("reading_parts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    question_number = Column(Integer, nullable=False)  # guruhning 1-chi savol raqami
    type = Column(SAEnum(QuestionTypeEnum), nullable=False)
    question_text = Column(Text, nullable=True)  # HTML (group-level matn)
    instruction = Column(Text, nullable=True)  # HTML instruction
    context = Column(Text, nullable=True)
    heading_options = Column(JSON, nullable=True)  # MATCHING_HEADINGS uchun
    table_data = Column(JSON, nullable=True)
    points = Column(Integer, default=1, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    part = relationship("ReadingPart", back_populates="question_groups")
    sub_questions = relationship(
        "SubQuestion",
        back_populates="group",
        cascade="all, delete-orphan",
        order_by="SubQuestion.question_number",
        lazy="selectin",
    )
    options = relationship(
        "QuestionOption",
        back_populates="group",
        cascade="all, delete-orphan",
        order_by="QuestionOption.order_index",
        lazy="selectin",
    )


# ---------------------------------------------------------------------------
# SubQuestion
# ---------------------------------------------------------------------------


class SubQuestion(Base):
    """Guruh ichidagi har bir alohida savol (global raqam 1–40)."""

    __tablename__ = "sub_questions"

    id = Column(Integer, primary_key=True, index=True)
    group_id = Column(
        Integer,
        ForeignKey("question_groups.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    question_number = Column(Integer, nullable=False, index=True)
    question_text = Column(Text, nullable=True)
    correct_answer = Column(String(500), nullable=True)  # userlarga berilmaydi
    explanation = Column(Text, nullable=True)
    from_passage = Column(Text, nullable=True)
    points = Column(Integer, default=1, nullable=False)

    group = relationship("QuestionGroup", back_populates="sub_questions")
    user_answers = relationship(
        "UserQuestionAnswer",
        back_populates="sub_question",
        cascade="all, delete-orphan",
    )


# ---------------------------------------------------------------------------
# QuestionOption
# ---------------------------------------------------------------------------


class QuestionOption(Base):
    """MCQ / Matching variantlari. option_key: 'A', 'B', 'C' ..."""

    __tablename__ = "question_options"

    id = Column(Integer, primary_key=True, index=True)
    group_id = Column(
        Integer,
        ForeignKey("question_groups.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    option_key = Column(String(10), nullable=False)
    option_text = Column(Text, nullable=False)
    is_correct = Column(Boolean, default=False, nullable=False)
    order_index = Column(Integer, default=0, nullable=False)
    explanation = Column(Text, nullable=True)
    from_passage = Column(Text, nullable=True)

    group = relationship("QuestionGroup", back_populates="options")


# ---------------------------------------------------------------------------
# UserTestAttempt
# ---------------------------------------------------------------------------


class UserTestAttempt(Base):
    """
    Foydalanuvchining bitta test urinishi.

    scope=FULL → butun test (3 part), barcha darajalar
    scope=PART → bitta passage,       PREMIUM / PRO
    mode=PRACTICE → cheksiz urinish   FREE+
    mode=EXAM     → faqat 1 marta     PRO only
    """

    __tablename__ = "user_test_attempts"

    id = Column(Integer, primary_key=True, index=True)

    user_id = Column(
        UUIDType,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    test_id = Column(
        String(8),  # ✅ TO'G'RI
        ForeignKey("reading_tests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Qaysi part (PART scope da) — FULL da NULL
    part_id = Column(
        Integer,
        ForeignKey("reading_parts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    mode = Column(
        SAEnum(AttemptModeEnum),
        default=AttemptModeEnum.PRACTICE,
        nullable=False,
    )

    # FULL yoki PART
    scope = Column(
        SAEnum(AttemptScopeEnum),
        default=AttemptScopeEnum.FULL,
        nullable=False,
    )

    started_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at = Column(DateTime(timezone=True), nullable=True)
    is_completed = Column(Boolean, default=False, nullable=False)

    # Denormalized natija (topshirilgandan keyin yoziladi)
    total_questions = Column(Integer, default=0, nullable=False)
    correct_count = Column(Integer, default=0, nullable=False)
    incorrect_count = Column(Integer, default=0, nullable=False)
    unanswered_count = Column(Integer, default=0, nullable=False)
    score_percent = Column(Float, default=0.0, nullable=False)
    band_score = Column(Float, nullable=True)  # IELTS Band 0.0–9.0
    time_spent_sec = Column(Integer, nullable=True)

    user = relationship("User", back_populates="test_attempts")
    test = relationship("ReadingTest", back_populates="attempts")
    part = relationship("ReadingPart", foreign_keys=[part_id])
    question_answers = relationship(
        "UserQuestionAnswer",
        back_populates="attempt",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    analysis = relationship(
        "AttemptAnalysis",
        back_populates="attempt",
        uselist=False,
        cascade="all, delete-orphan",
    )


# ---------------------------------------------------------------------------
# UserQuestionAnswer
# ---------------------------------------------------------------------------


class UserQuestionAnswer(Base):
    """Foydalanuvchining har bir SubQuestion ga bergan javobi."""

    __tablename__ = "user_question_answers"

    id = Column(Integer, primary_key=True, index=True)
    attempt_id = Column(
        Integer,
        ForeignKey("user_test_attempts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sub_question_id = Column(
        Integer,
        ForeignKey("sub_questions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    given_answer = Column(String(500), nullable=True)
    status = Column(
        SAEnum(AnswerStatusEnum),
        default=AnswerStatusEnum.UNANSWERED,
        nullable=False,
    )
    answered_at = Column(DateTime(timezone=True), nullable=True)

    attempt = relationship("UserTestAttempt", back_populates="question_answers")
    sub_question = relationship("SubQuestion", back_populates="user_answers")


# ---------------------------------------------------------------------------
# AttemptAnalysis
# ---------------------------------------------------------------------------


class AttemptAnalysis(Base):
    """
    Attempt topshirilgandan so'ng avtomatik hisoblangan batafsil tahlil.
    UserTestAttempt bilan 1-to-1 munosabat.
    """

    __tablename__ = "attempt_analyses"

    id = Column(Integer, primary_key=True, index=True)
    attempt_id = Column(
        Integer,
        ForeignKey("user_test_attempts.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # {"MULTIPLE_CHOICE": {"correct": 3, "incorrect": 1, "unanswered": 0, "total": 4, "accuracy_pct": 75.0}, ...}
    question_type_breakdown = Column(JSON, nullable=False, default=dict)

    # {"1": {"correct": 5, "incorrect": 2, "unanswered": 1, "total": 8, "accuracy_pct": 62.5, "title": "..."}, ...}
    part_breakdown = Column(JSON, nullable=False, default=dict)

    # ["TRUE_FALSE_NOT_GIVEN", "MATCHING_HEADINGS"]  — accuracy < 60%
    weak_question_types = Column(JSON, nullable=False, default=list)

    per_question_detail = Column(JSON, nullable=False, default=list)

    avg_time_per_question_sec = Column(Float, nullable=True)

    attempt = relationship("UserTestAttempt", back_populates="analysis")
