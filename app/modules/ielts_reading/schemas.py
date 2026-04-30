# app/modules/ielts/reading/schemas.py

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, field_validator

from .models import (
    AnswerStatusEnum,
    AttemptModeEnum,
    AttemptScopeEnum,
    DifficultyEnum,
    QuestionTypeEnum,
    SubscriptionTierEnum,
)


# ══════════════════════════════════════════════════════════════════════
# Option schemas
# ══════════════════════════════════════════════════════════════════════


class OptionBase(BaseModel):
    option_key: str
    option_text: str
    order_index: int = 0


class OptionCreate(OptionBase):
    is_correct: bool = False
    explanation: Optional[str] = None
    from_passage: Optional[str] = None


class OptionOut(OptionBase):
    """Sent to users — correct answer is hidden."""

    id: int

    model_config = {"from_attributes": True}


class OptionWithAnswerOut(OptionOut):
    """Sent to admin / result screen — includes correct flag and explanation."""

    is_correct: bool
    explanation: Optional[str] = None
    from_passage: Optional[str] = None


# ══════════════════════════════════════════════════════════════════════
# SubQuestion schemas
# ══════════════════════════════════════════════════════════════════════


class SubQuestionBase(BaseModel):
    question_number: int
    question_text: Optional[str] = None
    points: int = 1


class SubQuestionCreate(SubQuestionBase):
    correct_answer: Optional[str] = None
    explanation: Optional[str] = None
    from_passage: Optional[str] = None


class SubQuestionOut(SubQuestionBase):
    """Sent to users — correct answer is hidden."""

    id: int

    model_config = {"from_attributes": True}


class SubQuestionWithAnswerOut(SubQuestionOut):
    """Sent to admin / result screen — includes correct answer."""

    correct_answer: Optional[str] = None
    explanation: Optional[str] = None
    from_passage: Optional[str] = None


# ══════════════════════════════════════════════════════════════════════
# QuestionGroup schemas
# ══════════════════════════════════════════════════════════════════════


class QuestionGroupBase(BaseModel):
    question_number: int
    type: QuestionTypeEnum
    instruction: Optional[str] = None
    question_text: Optional[str] = None
    context: Optional[str] = None
    heading_options: Optional[Any] = None
    table_data: Optional[Any] = None
    points: int = 1
    is_active: bool = True


class QuestionGroupCreate(QuestionGroupBase):
    sub_questions: List[SubQuestionCreate] = []
    options: List[OptionCreate] = []


class QuestionGroupOut(QuestionGroupBase):
    """Sent to users."""

    id: int
    sub_questions: List[SubQuestionOut] = []
    options: List[OptionOut] = []

    model_config = {"from_attributes": True}


class QuestionGroupWithAnswersOut(QuestionGroupBase):
    """Sent to admin / result screen."""

    id: int
    sub_questions: List[SubQuestionWithAnswerOut] = []
    options: List[OptionWithAnswerOut] = []

    model_config = {"from_attributes": True}


# ══════════════════════════════════════════════════════════════════════
# ReadingPart schemas
# ══════════════════════════════════════════════════════════════════════


class ReadingPartBase(BaseModel):
    part: int
    title: str
    content: str
    time_limit_minutes: int = 20
    difficulty: DifficultyEnum = DifficultyEnum.MEDIUM
    is_active: bool = True
    total_questions: int = 0


class ReadingPartCreate(ReadingPartBase):
    question_groups: List[QuestionGroupCreate] = []


class ReadingPartOut(ReadingPartBase):
    """Sent to users."""

    id: int
    question_groups: List[QuestionGroupOut] = []
    created_at: datetime

    model_config = {"from_attributes": True}


class ReadingPartWithAnswersOut(ReadingPartBase):
    """Sent to admin / result screen."""

    id: int
    question_groups: List[QuestionGroupWithAnswersOut] = []
    created_at: datetime

    model_config = {"from_attributes": True}


# ══════════════════════════════════════════════════════════════════════
# ReadingTest schemas
# ══════════════════════════════════════════════════════════════════════


class ReadingTestBase(BaseModel):
    global_title: str
    is_active: bool = True
    is_free: bool = False
    # Testdagi asosiy question type lari (filtrlash uchun meta)
    question_types: List[QuestionTypeEnum] = []


class ReadingTestCreate(ReadingTestBase):
    parts: List[ReadingPartCreate] = []


class ReadingTestOut(ReadingTestBase):
    """Sent to users — passage + questions, no correct answers."""

    id: str
    parts: List[ReadingPartOut] = []
    created_at: datetime

    model_config = {"from_attributes": True}


class ReadingTestListOut(ReadingTestBase):
    """Lightweight schema for list endpoints — no passage content."""

    id: str
    created_at: datetime
    parts_count: int = 0

    model_config = {"from_attributes": True}


# ══════════════════════════════════════════════════════════════════════
# Attempt schemas
# ══════════════════════════════════════════════════════════════════════


class AnswerIn(BaseModel):
    """Single question answer submitted by the user."""

    sub_question_id: int
    given_answer: Optional[str] = None


class StartAttemptIn(BaseModel):
    test_id: str
    # PRACTICE (default) — cheksiz urinish, javoblar darhol ko'rinadi (FREE+)
    # EXAM               — faqat 1 marta, haqiqiy IELTS sharoiti  (PRO only)
    mode: AttemptModeEnum = AttemptModeEnum.PRACTICE
    # FULL (default) — butun test (barcha darajalar)
    # PART           — bitta passage  (PREMIUM / PRO only)
    scope: AttemptScopeEnum = AttemptScopeEnum.FULL
    # scope=PART da majburiy: qaysi part
    part_id: Optional[int] = None

    @field_validator("part_id")
    @classmethod
    def part_id_required_for_part_scope(
        cls, v: Optional[int], info: Any
    ) -> Optional[int]:
        scope = info.data.get("scope")
        if scope == AttemptScopeEnum.PART and v is None:
            raise ValueError("part_id is required when scope is PART.")
        return v


class StartAttemptOut(BaseModel):
    attempt_id: int
    started_at: datetime
    test_id: str
    mode: AttemptModeEnum
    scope: AttemptScopeEnum
    part_id: Optional[int] = None

    model_config = {"from_attributes": True}


class SubmitAnswersIn(BaseModel):
    attempt_id: int
    answers: List[AnswerIn]

    @field_validator("answers")
    @classmethod
    def answers_not_empty(cls, v: list) -> list:
        if not v:
            raise ValueError("At least one answer must be provided.")
        return v


class QuestionResultOut(BaseModel):
    """Per-question breakdown returned in the result."""

    sub_question_id: int
    question_number: int
    given_answer: Optional[str] = None
    correct_answer: Optional[str] = None
    status: AnswerStatusEnum
    explanation: Optional[str] = None
    from_passage: Optional[str] = None


class AttemptResultOut(BaseModel):
    """Full graded result for a completed attempt."""

    attempt_id: int
    test_id: str
    user_id: UUID
    mode: AttemptModeEnum
    scope: AttemptScopeEnum
    part_id: Optional[int] = None
    started_at: datetime
    finished_at: Optional[datetime] = None
    is_completed: bool
    total_questions: int
    correct_count: int
    incorrect_count: int
    unanswered_count: int
    score_percent: float
    band_score: Optional[float] = None
    time_spent_sec: Optional[int] = None
    question_results: List[QuestionResultOut] = []

    model_config = {"from_attributes": True}


class AttemptHistoryOut(BaseModel):
    """Single entry in a user's attempt history list."""

    attempt_id: int
    test_id: str
    global_title: str
    mode: AttemptModeEnum
    scope: AttemptScopeEnum
    part_id: Optional[int] = None
    started_at: datetime
    finished_at: Optional[datetime] = None
    is_completed: bool
    score_percent: float
    band_score: Optional[float] = None
    correct_count: int
    total_questions: int

    model_config = {"from_attributes": True}


# ══════════════════════════════════════════════════════════════════════
# Analysis schemas
# ══════════════════════════════════════════════════════════════════════


class QuestionTypeStatOut(BaseModel):
    """Bitta question type uchun statistika."""

    correct: int
    incorrect: int
    unanswered: int
    total: int
    accuracy_pct: float


class PartStatOut(BaseModel):
    """Bitta passage (part) uchun statistika."""

    title: str
    correct: int
    incorrect: int
    unanswered: int
    total: int
    accuracy_pct: float


class PerQuestionDetailOut(BaseModel):
    """Har bir savol uchun batafsil tahlil."""

    question_number: int
    question_type: str
    part: int
    part_title: str
    status: AnswerStatusEnum
    given_answer: Optional[str] = None
    correct_answer: Optional[str] = None
    explanation: Optional[str] = None
    from_passage: Optional[str] = None


class AttemptAnalysisOut(BaseModel):
    """
    Attempt tahlili — submit qilinganda avtomatik yaratiladi.
    GET /attempts/{attempt_id}/analysis orqali qaytariladi.
    """

    attempt_id: int
    created_at: datetime

    question_type_breakdown: Dict[str, QuestionTypeStatOut]
    part_breakdown: Dict[str, PartStatOut]
    weak_question_types: List[str]
    per_question_detail: List[PerQuestionDetailOut]
    avg_time_per_question_sec: Optional[float] = None

    model_config = {"from_attributes": True}


# ══════════════════════════════════════════════════════════════════════
# Progress schemas
# ══════════════════════════════════════════════════════════════════════


class ProgressPointOut(BaseModel):
    """Bitta attempt uchun progress nuqtasi (grafik uchun)."""

    attempt_id: int
    test_id: str
    global_title: str
    mode: AttemptModeEnum
    scope: AttemptScopeEnum
    finished_at: datetime
    band_score: float
    score_percent: float
    correct_count: int
    total_questions: int
    time_spent_sec: Optional[int] = None


class WeakTypeProgressOut(BaseModel):
    """Vaqt o'tishi bilan question type accuracy o'zgarishi."""

    question_type: str
    trend: List[Dict[str, Any]]


class ProgressOut(BaseModel):
    """
    Foydalanuvchining umumiy progress tahlili.
    GET /attempts/progress orqali qaytariladi.
    """

    total_attempts: int
    best_band_score: Optional[float] = None
    latest_band_score: Optional[float] = None
    avg_band_score: Optional[float] = None

    band_trend: List[ProgressPointOut]
    overall_type_accuracy: Dict[str, float]
    top_weak_types: List[str]
    type_trends: List[WeakTypeProgressOut]


# ══════════════════════════════════════════════════════════════════════
# Generic response wrapper
# ══════════════════════════════════════════════════════════════════════


class SuccessResponse(BaseModel):
    success: bool = True
    message: str = "OK"
    data: Optional[Any] = None
