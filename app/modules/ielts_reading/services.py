# app/modules/ielts/reading/services.py

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import random
import string
from typing import Dict, List, Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .models import (
    AnswerStatusEnum,
    AttemptAnalysis,
    AttemptModeEnum,
    AttemptScopeEnum,
    QuestionGroup,
    QuestionOption,
    QuestionTypeEnum,
    ReadingPart,
    ReadingTest,
    SubQuestion,
    SubscriptionTierEnum,
    UserQuestionAnswer,
    UserRoleEnum,
    UserTestAttempt,
)
from .schemas import (
    AttemptAnalysisOut,
    AttemptHistoryOut,
    AttemptResultOut,
    PartStatOut,
    PerQuestionDetailOut,
    ProgressOut,
    ProgressPointOut,
    QuestionResultOut,
    QuestionTypeStatOut,
    ReadingTestCreate,
    SubmitAnswersIn,
    WeakTypeProgressOut,
)


# ══════════════════════════════════════════════════════════════════════
# IELTS Band Score table  (Academic Reading — official scale)
# ══════════════════════════════════════════════════════════════════════

_BAND_TABLE: list[tuple[int, float]] = [
    (39, 9.0),
    (37, 8.5),
    (35, 8.0),
    (33, 7.5),
    (30, 7.0),
    (27, 6.5),
    (23, 6.0),
    (19, 5.5),
    (15, 5.0),
    (13, 4.5),
    (10, 4.0),
    (8, 3.5),
    (6, 3.0),
    (4, 2.5),
    (0, 2.0),
]

_WEAK_THRESHOLD = 60.0  # accuracy % dan past bo'lsa "zaif" hisoblanadi


def _generate_test_id() -> str:
    """8 xonali tasodifiy alfanumerik ID (harf + raqam aralash)."""
    chars = string.ascii_uppercase + string.digits  # A-Z, 0-9
    return "".join(random.choices(chars, k=8))


def _calculate_band(correct: int) -> float:
    for threshold, band in _BAND_TABLE:
        if correct >= threshold:
            return band
    return 2.0


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _accuracy(correct: int, total: int) -> float:
    return round(correct / total * 100, 1) if total else 0.0


# ══════════════════════════════════════════════════════════════════════
# Subscription permission helpers
# ══════════════════════════════════════════════════════════════════════

# Tier ierarxiyasi: PRO > PREMIUM > FREE
_TIER_RANK: Dict[SubscriptionTierEnum, int] = {
    SubscriptionTierEnum.FREE: 0,
    SubscriptionTierEnum.PREMIUM: 1,
    SubscriptionTierEnum.PRO: 2,
}


def _tier_gte(user_tier: SubscriptionTierEnum, required: SubscriptionTierEnum) -> bool:
    """Foydalanuvchi daraja talab qilingan darajaga teng yoki yuqorimi."""
    return _TIER_RANK[user_tier] >= _TIER_RANK[required]


def _assert_subscription(
    user_tier: SubscriptionTierEnum,
    required: SubscriptionTierEnum,
    feature_name: str,
) -> None:
    """Talab qilingan darajaga ega bo'lmasa HTTP 403 ko'taradi."""
    if not _tier_gte(user_tier, required):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"'{feature_name}' xususiyati {required.value} obuna talab qiladi. "
                f"Sizning darajangiz: {user_tier.value}."
            ),
        )


# ══════════════════════════════════════════════════════════════════════
# ReadingTestService
# ══════════════════════════════════════════════════════════════════════


class ReadingTestService:
    # ──────────────────────────────────────────────────────────────────
    # CREATE
    # ──────────────────────────────────────────────────────────────────

    @staticmethod
    async def create_test(db: AsyncSession, data: ReadingTestCreate) -> ReadingTest:
        test = ReadingTest(
            global_title=data.global_title,
            is_active=data.is_active,
            is_free=data.is_free,
            question_types=[qt.value for qt in data.question_types],
        )
        db.add(test)
        await db.flush()

        for part_data in data.parts:
            part = ReadingPart(
                test_id=test.id,
                part=part_data.part,
                title=part_data.title,
                content=part_data.content,
                time_limit_minutes=part_data.time_limit_minutes,
                difficulty=part_data.difficulty,
                is_active=part_data.is_active,
                total_questions=part_data.total_questions,
            )
            db.add(part)
            
            await db.flush()

            for g_data in part_data.question_groups:
                group = QuestionGroup(
                    part_id=part.id,
                    question_number=g_data.question_number,
                    type=g_data.type,
                    instruction=g_data.instruction,
                    question_text=g_data.question_text,
                    context=g_data.context,
                    heading_options=getattr(g_data, "heading_options", None),
                    table_data=getattr(g_data, "table_data", None),
                    points=g_data.points,
                    is_active=g_data.is_active,
                )
                db.add(group)
                await db.flush()

                for sq in g_data.sub_questions:
                    db.add(
                        SubQuestion(
                            group_id=group.id,
                            question_number=sq.question_number,
                            question_text=sq.question_text,
                            correct_answer=sq.correct_answer,
                            explanation=sq.explanation,
                            from_passage=sq.from_passage,
                            points=sq.points,
                        )
                    )

                for opt in g_data.options:
                    db.add(
                        QuestionOption(
                            group_id=group.id,
                            option_key=opt.option_key,
                            option_text=opt.option_text,
                            is_correct=opt.is_correct,
                            order_index=opt.order_index,
                            explanation=opt.explanation,
                            from_passage=opt.from_passage,
                        )
                    )

        await db.commit()

        result = await db.execute(
            select(ReadingTest)
            .options(
                selectinload(ReadingTest.parts).options(
                    selectinload(ReadingPart.question_groups).options(
                        selectinload(QuestionGroup.sub_questions),
                        selectinload(QuestionGroup.options),
                    )
                )
            )
            .where(ReadingTest.id == test.id)
        )
        return result.scalar_one()

    # ──────────────────────────────────────────────────────────────────
    # READ
    # ──────────────────────────────────────────────────────────────────

    @staticmethod
    async def get_test(
        db: AsyncSession,
        test_id: str,
        user_tier: SubscriptionTierEnum = SubscriptionTierEnum.FREE,
    ) -> ReadingTest:
        """
        Testni qaytaradi.
        Agar test is_free=False bo'lsa va foydalanuvchi FREE bo'lsa → 403.
        """
        result = await db.execute(
            select(ReadingTest)
            .options(
                selectinload(ReadingTest.parts).options(
                    selectinload(ReadingPart.question_groups).options(
                        selectinload(QuestionGroup.sub_questions),
                        selectinload(QuestionGroup.options),
                    )
                )
            )
            .where(
                ReadingTest.id == test_id,
                ReadingTest.is_active == True,
            )
        )
        test = result.scalar_one_or_none()
        if not test:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Test not found.")

        # Obuna tekshiruvi
        if not test.is_free and user_tier == SubscriptionTierEnum.FREE:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Bu test PREMIUM yoki PRO obuna talab qiladi. "
                    "Tekin testlarni ko'rish uchun is_free=true filtrlang."
                ),
            )
        return test

    @staticmethod
    async def list_tests(
        db: AsyncSession,
        skip: int = 0,
        limit: int = 20,
        user_tier: SubscriptionTierEnum = SubscriptionTierEnum.FREE,
        question_type_filter: Optional[QuestionTypeEnum] = None,
        free_only: bool = False,
    ):
        """
        Aktiv testlar ro'yxatini qaytaradi.

        - user_tier=FREE  → faqat is_free=True testlar
        - question_type_filter → JSON array ichida ushbu type bor testlar
        - free_only=True  → majburan faqat tekin testlar (FREE tier uchun avtomatik)
        """
        query = (
            select(ReadingTest)
            .options(selectinload(ReadingTest.parts))
            .where(ReadingTest.is_active == True)
        )

        # FREE foydalanuvchilar faqat tekin testlarni ko'ra oladi
        if user_tier == SubscriptionTierEnum.FREE or free_only:
            query = query.where(ReadingTest.is_free == True)

        # Question type bo'yicha filtrlash (JSON array contains)
        if question_type_filter is not None:
            # PostgreSQL JSON array ichida qidirish
            query = query.where(
                ReadingTest.question_types.contains([question_type_filter.value])
            )

        result = await db.execute(query.offset(skip).limit(limit))
        return list(result.scalars().all())

    # ──────────────────────────────────────────────────────────────────
    # DELETE (soft)
    # ──────────────────────────────────────────────────────────────────

    @staticmethod
    async def delete_test(db: AsyncSession, test_id: str) -> None:
        """Soft-deletes a test. Access control: ADMIN only (enforced in router)."""
        # Admin uchun obuna tekshiruvi kerak emas
        result = await db.execute(
            select(ReadingTest).where(
                ReadingTest.id == test_id,
                ReadingTest.is_active == True,
            )
        )
        test = result.scalar_one_or_none()
        if not test:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Test not found.")
        test.is_active = False
        await db.commit()


# ══════════════════════════════════════════════════════════════════════
# AttemptService
# ══════════════════════════════════════════════════════════════════════


class AttemptService:
    # ──────────────────────────────────────────────────────────────────
    # START
    # ──────────────────────────────────────────────────────────────────

    @staticmethod
    async def start(
        db: AsyncSession,
        user_id: UUID,
        test_id: str,
        mode: AttemptModeEnum = AttemptModeEnum.PRACTICE,
        scope: AttemptScopeEnum = AttemptScopeEnum.FULL,
        part_id: Optional[int] = None,
        user_tier: SubscriptionTierEnum = SubscriptionTierEnum.FREE,
    ) -> UserTestAttempt:
        """
        Yangi attempt yaratadi.

        Obuna qoidalari:
          FREE    → faqat PRACTICE + FULL scope, faqat is_free testlar
          PREMIUM → PRACTICE + FULL yoki PART scope, barcha testlar
          PRO     → hammasi + EXAM mode

        EXAM mode qoidasi:
          Bir xil testga faqat 1 marta EXAM attempt (xoh tugallangan, xoh yo'q).
          Boshlangan EXAM attemptni davom ettirish uchun mavjud attempt_id qaytariladi.
        """
        # ── Obuna tekshiruvlari ────────────────────────────────────────

        # 1) EXAM mode — PRO only
        if mode == AttemptModeEnum.EXAM:
            _assert_subscription(user_tier, SubscriptionTierEnum.PRO, "EXAM mode")

        # 2) PART scope — PREMIUM+ only
        if scope == AttemptScopeEnum.PART:
            _assert_subscription(
                user_tier, SubscriptionTierEnum.PREMIUM, "Part-level attempt"
            )

        # 3) Test mavjud va obunaga mos ekanini tekshir
        test = await ReadingTestService.get_test(db, test_id, user_tier=user_tier)

        # 4) PART scope: part_id testga tegishli ekanini tekshir
        if scope == AttemptScopeEnum.PART:
            if part_id is None:
                raise ValueError("scope=PART bo'lganda part_id majburiy.")
            part_result = await db.execute(
                select(ReadingPart).where(
                    ReadingPart.id == part_id,
                    ReadingPart.test_id == test_id,
                    ReadingPart.is_active == True,
                )
            )
            if not part_result.scalar_one_or_none():
                raise ValueError(
                    f"part_id={part_id} ushbu testga tegishli emas yoki faol emas."
                )

        # ── EXAM: takror urinishni taqiqlash ──────────────────────────
        if mode == AttemptModeEnum.EXAM:
            exam_filter = [
                UserTestAttempt.user_id == user_id,
                UserTestAttempt.test_id == test_id,
                UserTestAttempt.mode == AttemptModeEnum.EXAM,
            ]
            if scope == AttemptScopeEnum.PART:
                exam_filter.append(UserTestAttempt.part_id == part_id)

            existing_result = await db.execute(
                select(UserTestAttempt).where(*exam_filter)
            )
            existing = existing_result.scalar_one_or_none()
            if existing:
                if existing.is_completed:
                    raise ValueError(
                        "Siz bu testni allaqachon EXAM rejimida topshirgansiz. "
                        "Har bir test faqat bir marta topshirilishi mumkin."
                    )
                else:
                    raise ValueError(
                        f"Siz bu testni EXAM rejimida allaqachon boshlagansiz "
                        f"(attempt_id={existing.id}). "
                        f"Avval mavjud attemptni tugatib yuboring."
                    )

        attempt = UserTestAttempt(
            user_id=user_id,
            test_id=test_id,
            part_id=part_id if scope == AttemptScopeEnum.PART else None,
            mode=mode,
            scope=scope,
        )
        db.add(attempt)
        await db.commit()
        await db.refresh(attempt)
        return attempt

    # ──────────────────────────────────────────────────────────────────
    # SUBMIT
    # ──────────────────────────────────────────────────────────────────

    @staticmethod
    async def submit(
        db: AsyncSession,
        user_id: UUID,
        payload: SubmitAnswersIn,
    ) -> UserTestAttempt:
        """
        Barcha javoblarni baholaydi, band score hisoblaydi,
        attemptni yakunlaydi va AttemptAnalysis yaratadi.
        Attempt faqat bir marta topshirilishi mumkin.
        """
        result = await db.execute(
            select(UserTestAttempt).where(
                UserTestAttempt.id == payload.attempt_id,
                UserTestAttempt.user_id == user_id,
            )
        )
        attempt = result.scalar_one_or_none()

        if not attempt:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Attempt not found.")
        if attempt.is_completed:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail="This attempt has already been submitted.",
            )

        # Barcha sub-savollarni bir so'rovda ol
        sq_ids = [a.sub_question_id for a in payload.answers]
        sq_result = await db.execute(
            select(SubQuestion).where(SubQuestion.id.in_(sq_ids))
        )
        sq_map: Dict[int, SubQuestion] = {sq.id: sq for sq in sq_result.scalars().all()}

        correct = incorrect = 0
        answer_objects: List[UserQuestionAnswer] = []

        for ans in payload.answers:
            sq = sq_map.get(ans.sub_question_id)
            if not sq:
                continue

            given = (ans.given_answer or "").strip().lower()
            correct_a = (sq.correct_answer or "").strip().lower()

            if not given:
                ans_status = AnswerStatusEnum.UNANSWERED
            elif given == correct_a:
                ans_status = AnswerStatusEnum.CORRECT
                correct += 1
            else:
                ans_status = AnswerStatusEnum.INCORRECT
                incorrect += 1

            ua = UserQuestionAnswer(
                attempt_id=attempt.id,
                sub_question_id=sq.id,
                given_answer=ans.given_answer,
                status=ans_status,
                answered_at=_utcnow(),
            )
            db.add(ua)
            answer_objects.append(ua)

        total = len(payload.answers)
        unanswered = total - correct - incorrect
        now = _utcnow()

        attempt.is_completed = True
        attempt.finished_at = now
        attempt.total_questions = total
        attempt.correct_count = correct
        attempt.incorrect_count = incorrect
        attempt.unanswered_count = unanswered
        attempt.score_percent = round(correct / total * 100, 1) if total else 0.0
        attempt.band_score = _calculate_band(correct)

        if attempt.started_at:
            started = attempt.started_at
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
            attempt.time_spent_sec = int((now - started).total_seconds())

        await db.flush()

        await AnalysisService.create_for_attempt(
            db=db,
            attempt=attempt,
            sq_map=sq_map,
            answer_statuses={
                ans.sub_question_id: ans.given_answer for ans in payload.answers
            },
        )

        await db.commit()

        # commit dan keyin eager load bilan qayta yukla
        refreshed = await db.execute(
            select(UserTestAttempt)
            .options(
                selectinload(UserTestAttempt.question_answers).selectinload(
                    UserQuestionAnswer.sub_question
                )
            )
            .where(UserTestAttempt.id == attempt.id)
        )
        return refreshed.scalar_one()

    # ──────────────────────────────────────────────────────────────────
    # GET RESULT  (role-aware)
    # ──────────────────────────────────────────────────────────────────

    @staticmethod
    async def get_result(
        db: AsyncSession,
        attempt_id: int,
        user_id: UUID,
        role: UserRoleEnum = UserRoleEnum.USER,
    ) -> AttemptResultOut:
        """
        Attempt to'liq natijasini qaytaradi.
        USER           — faqat o'z attemptini ko'ra oladi.
        ADMIN / TEACHER — istalgan attemptni ko'ra oladi.
        """
        is_privileged = role in (UserRoleEnum.ADMIN, UserRoleEnum.TEACHER)

        query = (
            select(UserTestAttempt)
            .options(
                selectinload(UserTestAttempt.question_answers).selectinload(
                    UserQuestionAnswer.sub_question
                )
            )
            .where(UserTestAttempt.id == attempt_id)
        )
        if not is_privileged:
            query = query.where(UserTestAttempt.user_id == user_id)

        result = await db.execute(query)
        attempt = result.scalar_one_or_none()

        if not attempt:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Result not found.")

        question_results: List[QuestionResultOut] = []
        for ua in attempt.question_answers:
            sq: SubQuestion = ua.sub_question
            question_results.append(
                QuestionResultOut(
                    sub_question_id=sq.id,
                    question_number=sq.question_number,
                    given_answer=ua.given_answer,
                    correct_answer=sq.correct_answer,
                    status=ua.status,
                    explanation=sq.explanation,
                    from_passage=sq.from_passage,
                )
            )

        return AttemptResultOut(
            attempt_id=attempt.id,
            test_id=attempt.test_id,
            user_id=attempt.user_id,
            mode=attempt.mode,
            scope=attempt.scope,
            part_id=attempt.part_id,
            started_at=attempt.started_at,
            finished_at=attempt.finished_at,
            is_completed=attempt.is_completed,
            total_questions=attempt.total_questions,
            correct_count=attempt.correct_count,
            incorrect_count=attempt.incorrect_count,
            unanswered_count=attempt.unanswered_count,
            score_percent=attempt.score_percent,
            band_score=attempt.band_score,
            time_spent_sec=attempt.time_spent_sec,
            question_results=sorted(question_results, key=lambda r: r.question_number),
        )

    # ──────────────────────────────────────────────────────────────────
    # HISTORY — current user
    # ──────────────────────────────────────────────────────────────────

    @staticmethod
    async def user_history(
        db: AsyncSession,
        user_id: UUID,
        skip: int = 0,
        limit: int = 20,
    ) -> List[AttemptHistoryOut]:
        """Foydalanuvchining o'z attempt tarixini qaytaradi, yangirog'i birinchi."""
        result = await db.execute(
            select(UserTestAttempt, ReadingTest.global_title)
            .join(ReadingTest, ReadingTest.id == UserTestAttempt.test_id)
            .where(UserTestAttempt.user_id == user_id)
            .order_by(UserTestAttempt.started_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return [
            AttemptHistoryOut(
                attempt_id=a.id,
                test_id=a.test_id,
                global_title=title,
                mode=a.mode,
                scope=a.scope,
                part_id=a.part_id,
                started_at=a.started_at,
                finished_at=a.finished_at,
                is_completed=a.is_completed,
                score_percent=a.score_percent,
                band_score=a.band_score,
                correct_count=a.correct_count,
                total_questions=a.total_questions,
            )
            for a, title in result.all()
        ]

    # ──────────────────────────────────────────────────────────────────
    # HISTORY — all users  (ADMIN / TEACHER)
    # ──────────────────────────────────────────────────────────────────

    @staticmethod
    async def all_history(
        db: AsyncSession,
        filter_user_id: Optional[UUID] = None,
        skip: int = 0,
        limit: int = 20,
    ) -> List[AttemptHistoryOut]:
        """
        Barcha foydalanuvchilarning attempt tarixini qaytaradi.
        Access control: ADMIN yoki TEACHER (router da tekshiriladi).
        """
        query = (
            select(UserTestAttempt, ReadingTest.global_title)
            .join(ReadingTest, ReadingTest.id == UserTestAttempt.test_id)
            .order_by(UserTestAttempt.started_at.desc())
        )
        if filter_user_id is not None:
            query = query.where(UserTestAttempt.user_id == filter_user_id)

        result = await db.execute(query.offset(skip).limit(limit))
        return [
            AttemptHistoryOut(
                attempt_id=a.id,
                test_id=a.test_id,
                global_title=title,
                mode=a.mode,
                scope=a.scope,
                part_id=a.part_id,
                started_at=a.started_at,
                finished_at=a.finished_at,
                is_completed=a.is_completed,
                score_percent=a.score_percent,
                band_score=a.band_score,
                correct_count=a.correct_count,
                total_questions=a.total_questions,
            )
            for a, title in result.all()
        ]


# ══════════════════════════════════════════════════════════════════════
# AnalysisService
# ══════════════════════════════════════════════════════════════════════


class AnalysisService:
    # ──────────────────────────────────────────────────────────────────
    # CREATE  (submit dan avtomatik chaqiriladi)
    # ──────────────────────────────────────────────────────────────────

    @staticmethod
    async def create_for_attempt(
        db: AsyncSession,
        attempt: UserTestAttempt,
        sq_map: Dict[int, SubQuestion],
        answer_statuses: Dict[int, Optional[str]],  # sub_question_id → given_answer
    ) -> AttemptAnalysis:
        """
        Attempt topshirilgandan so'ng chaqiriladi.
        SubQuestion → QuestionGroup → ReadingPart zanjiri orqali
        har bir savol uchun to'liq tahlil yig'adi va AttemptAnalysis saqlaydi.
        """
        group_ids = {sq.group_id for sq in sq_map.values()}
        groups_result = await db.execute(
            select(QuestionGroup).where(QuestionGroup.id.in_(group_ids))
        )
        group_map: Dict[int, QuestionGroup] = {
            g.id: g for g in groups_result.scalars().all()
        }

        part_ids = {g.part_id for g in group_map.values()}
        parts_result = await db.execute(
            select(ReadingPart).where(ReadingPart.id.in_(part_ids))
        )
        part_map: Dict[int, ReadingPart] = {
            p.id: p for p in parts_result.scalars().all()
        }

        type_stats: Dict[str, Dict[str, int]] = defaultdict(
            lambda: {"correct": 0, "incorrect": 0, "unanswered": 0, "total": 0}
        )
        part_stats: Dict[str, Dict] = {}
        per_question_detail: List[dict] = []

        for sq_id, sq in sq_map.items():
            group = group_map.get(sq.group_id)
            if not group:
                continue
            part = part_map.get(group.part_id)
            if not part:
                continue

            given = answer_statuses.get(sq_id)
            given_clean = (given or "").strip().lower()
            correct_a = (sq.correct_answer or "").strip().lower()

            if not given_clean:
                q_status = AnswerStatusEnum.UNANSWERED
            elif given_clean == correct_a:
                q_status = AnswerStatusEnum.CORRECT
            else:
                q_status = AnswerStatusEnum.INCORRECT

            type_key = group.type.value
            part_key = str(part.part)

            type_stats[type_key]["total"] += 1
            type_stats[type_key][q_status.value.lower()] += 1

            if part_key not in part_stats:
                part_stats[part_key] = {
                    "title": part.title,
                    "correct": 0,
                    "incorrect": 0,
                    "unanswered": 0,
                    "total": 0,
                }
            part_stats[part_key]["total"] += 1
            part_stats[part_key][q_status.value.lower()] += 1

            per_question_detail.append(
                {
                    "question_number": sq.question_number,
                    "question_type": type_key,
                    "part": part.part,
                    "part_title": part.title,
                    "status": q_status.value,
                    "given_answer": given,
                    "correct_answer": sq.correct_answer,
                    "explanation": sq.explanation,
                    "from_passage": sq.from_passage,
                }
            )

        question_type_breakdown = {}
        weak_question_types = []

        for t_key, stats in type_stats.items():
            acc = _accuracy(stats["correct"], stats["total"])
            question_type_breakdown[t_key] = {
                "correct": stats["correct"],
                "incorrect": stats["incorrect"],
                "unanswered": stats["unanswered"],
                "total": stats["total"],
                "accuracy_pct": acc,
            }
            if acc < _WEAK_THRESHOLD:
                weak_question_types.append(t_key)

        part_breakdown = {}
        for p_key, stats in part_stats.items():
            part_breakdown[p_key] = {
                "title": stats["title"],
                "correct": stats["correct"],
                "incorrect": stats["incorrect"],
                "unanswered": stats["unanswered"],
                "total": stats["total"],
                "accuracy_pct": _accuracy(stats["correct"], stats["total"]),
            }

        avg_time = None
        if attempt.time_spent_sec and len(sq_map) > 0:
            avg_time = round(attempt.time_spent_sec / len(sq_map), 1)

        per_question_detail.sort(key=lambda x: x["question_number"])

        analysis = AttemptAnalysis(
            attempt_id=attempt.id,
            question_type_breakdown=question_type_breakdown,
            part_breakdown=part_breakdown,
            weak_question_types=weak_question_types,
            per_question_detail=per_question_detail,
            avg_time_per_question_sec=avg_time,
        )
        db.add(analysis)
        return analysis

    # ──────────────────────────────────────────────────────────────────
    # GET  (role-aware)
    # ──────────────────────────────────────────────────────────────────

    @staticmethod
    async def get_analysis(
        db: AsyncSession,
        attempt_id: int,
        user_id: UUID,
        role: UserRoleEnum = UserRoleEnum.USER,
    ) -> AttemptAnalysisOut:
        """
        Attempt tahlilini qaytaradi.
        USER — faqat o'z attemptini ko'ra oladi.
        ADMIN/TEACHER — istalgan attemptni ko'ra oladi.
        """
        is_privileged = role in (UserRoleEnum.ADMIN, UserRoleEnum.TEACHER)

        attempt_query = select(UserTestAttempt).where(UserTestAttempt.id == attempt_id)
        if not is_privileged:
            attempt_query = attempt_query.where(UserTestAttempt.user_id == user_id)
        attempt_result = await db.execute(attempt_query)
        attempt = attempt_result.scalar_one_or_none()

        if not attempt:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Attempt not found.")

        if not attempt.is_completed:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail="Attempt has not been submitted yet.",
            )

        analysis_result = await db.execute(
            select(AttemptAnalysis).where(AttemptAnalysis.attempt_id == attempt_id)
        )
        analysis = analysis_result.scalar_one_or_none()

        if not analysis:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                detail="Analysis not found for this attempt.",
            )

        return AttemptAnalysisOut(
            attempt_id=analysis.attempt_id,
            created_at=analysis.created_at,
            question_type_breakdown={
                k: QuestionTypeStatOut(**v)
                for k, v in analysis.question_type_breakdown.items()
            },
            part_breakdown={
                k: PartStatOut(**v) for k, v in analysis.part_breakdown.items()
            },
            weak_question_types=analysis.weak_question_types,
            per_question_detail=[
                PerQuestionDetailOut(**d) for d in analysis.per_question_detail
            ],
            avg_time_per_question_sec=analysis.avg_time_per_question_sec,
        )


# ══════════════════════════════════════════════════════════════════════
# ProgressService
# ══════════════════════════════════════════════════════════════════════


class ProgressService:
    @staticmethod
    async def get_progress(
        db: AsyncSession,
        user_id: UUID,
    ) -> ProgressOut:
        """
        Foydalanuvchining barcha tugallangan attemptlari bo'yicha
        umumiy progress tahlilini qaytaradi.
        PRACTICE va EXAM, FULL va PART attemptlari birgalikda hisoblanadi.
        """
        attempts_result = await db.execute(
            select(UserTestAttempt, ReadingTest.global_title)
            .join(ReadingTest, ReadingTest.id == UserTestAttempt.test_id)
            .where(
                UserTestAttempt.user_id == user_id,
                UserTestAttempt.is_completed == True,  # noqa: E712
                UserTestAttempt.band_score.isnot(None),
            )
            .order_by(UserTestAttempt.finished_at.asc())
        )
        rows = attempts_result.all()

        if not rows:
            return ProgressOut(
                total_attempts=0,
                band_trend=[],
                overall_type_accuracy={},
                top_weak_types=[],
                type_trends=[],
            )

        attempt_ids = [a.id for a, _ in rows]

        analyses_result = await db.execute(
            select(AttemptAnalysis).where(AttemptAnalysis.attempt_id.in_(attempt_ids))
        )
        analysis_map: Dict[int, AttemptAnalysis] = {
            an.attempt_id: an for an in analyses_result.scalars().all()
        }

        band_trend: List[ProgressPointOut] = []
        band_scores: List[float] = []

        for attempt, title in rows:
            if attempt.band_score is not None:
                band_scores.append(attempt.band_score)
                band_trend.append(
                    ProgressPointOut(
                        attempt_id=attempt.id,
                        test_id=attempt.test_id,
                        global_title=title,
                        mode=attempt.mode,
                        scope=attempt.scope,
                        finished_at=attempt.finished_at,
                        band_score=attempt.band_score,
                        score_percent=attempt.score_percent,
                        correct_count=attempt.correct_count,
                        total_questions=attempt.total_questions,
                        time_spent_sec=attempt.time_spent_sec,
                    )
                )

        cumulative_type: Dict[str, Dict[str, int]] = defaultdict(
            lambda: {"correct": 0, "total": 0}
        )
        type_trend_data: Dict[str, List[dict]] = defaultdict(list)

        for attempt, _ in rows:
            analysis = analysis_map.get(attempt.id)
            if not analysis:
                continue

            finished_str = (
                attempt.finished_at.isoformat() if attempt.finished_at else None
            )

            for t_key, stats in analysis.question_type_breakdown.items():
                cumulative_type[t_key]["correct"] += stats["correct"]
                cumulative_type[t_key]["total"] += stats["total"]

                if finished_str:
                    type_trend_data[t_key].append(
                        {
                            "finished_at": finished_str,
                            "accuracy_pct": stats["accuracy_pct"],
                            "attempt_id": attempt.id,
                        }
                    )

        overall_type_accuracy: Dict[str, float] = {
            t_key: _accuracy(vals["correct"], vals["total"])
            for t_key, vals in cumulative_type.items()
        }

        top_weak_types = sorted(
            [t for t, acc in overall_type_accuracy.items() if acc < _WEAK_THRESHOLD],
            key=lambda t: overall_type_accuracy[t],
        )[:3]

        type_trends = [
            WeakTypeProgressOut(question_type=t_key, trend=trend_list)
            for t_key, trend_list in type_trend_data.items()
        ]

        return ProgressOut(
            total_attempts=len(rows),
            best_band_score=max(band_scores) if band_scores else None,
            latest_band_score=band_scores[-1] if band_scores else None,
            avg_band_score=round(sum(band_scores) / len(band_scores), 2)
            if band_scores
            else None,
            band_trend=band_trend,
            overall_type_accuracy=overall_type_accuracy,
            top_weak_types=top_weak_types,
            type_trends=type_trends,
        )
