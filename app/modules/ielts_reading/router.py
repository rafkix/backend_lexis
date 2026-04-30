# modules/ielts_reading/router.py

from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.auth.dependencies import get_current_user, require_roles
from app.modules.auth.models import User

from .models import QuestionTypeEnum, SubscriptionTierEnum, UserRoleEnum
from .schemas import (
    AttemptAnalysisOut,
    AttemptHistoryOut,
    AttemptResultOut,
    ProgressOut,
    ReadingTestCreate,
    ReadingTestListOut,
    ReadingTestOut,
    StartAttemptIn,
    StartAttemptOut,
    SubmitAnswersIn,
    SuccessResponse,
)
from .services import (
    AnalysisService,
    AttemptService,
    ProgressService,
    ReadingTestService,
)


# ─── Shared response doc blocks ───────────────────────────────────────────────

_400 = {400: {"description": "Bad request — invalid input or business rule violation."}}
_401 = {401: {"description": "Unauthorized — Bearer token is missing or invalid."}}
_403 = {403: {"description": "Forbidden — insufficient role or subscription level."}}
_404 = {404: {"description": "Not found — the requested resource does not exist."}}
_422 = {
    422: {
        "description": "Validation error — request body or query params are malformed."
    }
}


# ─── Subscription tier helper ─────────────────────────────────────────────────


def _get_user_tier(current_user: User) -> SubscriptionTierEnum:
    """
    Resolves the subscription tier from the User model.
    Expects a `subscription_tier` field on User; defaults to FREE if absent.
    """
    tier_value = getattr(current_user, "subscription_tier", None)
    if tier_value is None:
        return SubscriptionTierEnum.FREE
    try:
        return SubscriptionTierEnum(str(tier_value).upper())
    except ValueError:
        return SubscriptionTierEnum.FREE


# ══════════════════════════════════════════════════════════════════════
# Router  →  /ielts/reading/...
# ══════════════════════════════════════════════════════════════════════

router = APIRouter(prefix="/ielts/reading", tags=["IELTS Reading"])


# ─────────────────────────────────────────────────────────────────────
# Tests  (public / tier-aware)
# ─────────────────────────────────────────────────────────────────────


@router.get(
    "/tests",
    response_model=List[ReadingTestListOut],
    summary="List active reading tests",
    description=(
        "Returns a paginated list of active reading tests. "
        "Passage content is **excluded** for performance.\n\n"
        "**Access rules by subscription tier:**\n"
        "- Unauthenticated or `FREE` users — free tests only (`is_free=true`)\n"
        "- `PREMIUM` / `PRO` users — all active tests\n\n"
        "**Filtering:**\n"
        "- `question_type` — returns only tests that contain the specified question type\n"
        "- `free_only=true` — forces free-tests-only regardless of subscription tier"
    ),
    responses={200: {"description": "List of tests returned successfully."}},
)
async def list_tests(
    skip: int = Query(0, ge=0, description="Number of records to skip."),
    limit: int = Query(
        20, ge=1, le=100, description="Maximum number of records to return."
    ),
    question_type: Optional[QuestionTypeEnum] = Query(
        None,
        description=(
            "Filter by question type (e.g. MULTIPLE_CHOICE, TRUE_FALSE_NOT_GIVEN). "
            "Only tests that contain this question type are returned."
        ),
    ),
    free_only: bool = Query(
        False,
        description="When true, only free tests are returned regardless of the user's subscription tier.",
    ),
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
):
    user_tier = (
        _get_user_tier(current_user) if current_user else SubscriptionTierEnum.FREE
    )
    tests = await ReadingTestService.list_tests(
        db,
        skip=skip,
        limit=limit,
        user_tier=user_tier,
        question_type_filter=question_type,
        free_only=free_only,
    )
    return [
        ReadingTestListOut(
            id=t.id,
            global_title=t.global_title,
            is_active=t.is_active,
            is_free=t.is_free,
            question_types=t.question_types or [],
            created_at=t.created_at,
            parts_count=len(t.parts),
        )
        for t in tests
    ]


@router.get(
    "/tests/{test_id}",
    response_model=ReadingTestOut,
    summary="Get a test by ID",
    description=(
        "Returns a single reading test with full passage content and all question groups.\n\n"
        "**Access rule:** Tests with `is_free=false` require a `PREMIUM` or `PRO` subscription.\n\n"
        "Correct answers are **never** exposed in this response."
    ),
    responses={
        200: {"description": "Test returned successfully."},
        **_403,
        **_404,
    },
)
async def get_test(
    test_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
):
    user_tier = (
        _get_user_tier(current_user) if current_user else SubscriptionTierEnum.FREE
    )
    return await ReadingTestService.get_test(db, test_id, user_tier=user_tier)


# ─────────────────────────────────────────────────────────────────────
# Attempts  (authenticated users)
# ─────────────────────────────────────────────────────────────────────


@router.post(
    "/attempts/start",
    response_model=StartAttemptOut,
    status_code=status.HTTP_201_CREATED,
    summary="Start a new attempt",
    description=(
        "Creates a new test attempt for the authenticated user and returns an `attempt_id` "
        "to be used in subsequent requests.\n\n"
        "**Subscription rules:**\n"
        "- `FREE` — PRACTICE mode only, FULL scope only, free tests only\n"
        "- `PREMIUM` — PRACTICE mode, FULL or PART scope, all tests\n"
        "- `PRO` — everything above plus EXAM mode (one submission per test)\n\n"
        "When `scope=PART`, the `part_id` field is required.\n\n"
        "**Requires USER role.**"
    ),
    responses={
        201: {"description": "Attempt created successfully."},
        **_400,
        **_401,
        **_403,
        **_404,
        **_422,
    },
)
async def start_attempt(
    payload: StartAttemptIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("USER")),
):
    user_tier = _get_user_tier(current_user)
    try:
        attempt = await AttemptService.start(
            db,
            user_id=current_user.id,
            test_id=payload.test_id,
            mode=payload.mode,
            scope=payload.scope,
            part_id=payload.part_id,
            user_tier=user_tier,
        )
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(e))
    return StartAttemptOut(
        attempt_id=attempt.id,
        started_at=attempt.started_at,
        test_id=attempt.test_id,
        mode=attempt.mode,
        scope=attempt.scope,
        part_id=attempt.part_id,
    )


@router.post(
    "/attempts/submit",
    response_model=AttemptResultOut,
    summary="Submit answers and receive a graded result",
    description=(
        "Submits all answers for an in-progress attempt, grades them, calculates the IELTS "
        "band score, persists a detailed `AttemptAnalysis`, and returns the full result.\n\n"
        "An attempt can only be submitted **once**. **Requires USER role.**"
    ),
    responses={
        200: {"description": "Answers submitted. Full graded result returned."},
        **_400,
        **_401,
        **_404,
        **_422,
    },
)
async def submit_attempt(
    payload: SubmitAnswersIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("USER")),
):
    try:
        attempt = await AttemptService.submit(
            db, user_id=current_user.id, payload=payload
        )
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(e))
    return await AttemptService.get_result(
        db, attempt_id=attempt.id, user_id=current_user.id, role=UserRoleEnum.USER
    )


# NOTE: Static paths (/history, /progress) must be declared BEFORE the dynamic
# /{attempt_id}/... routes so FastAPI resolves them correctly.


@router.get(
    "/attempts/history",
    response_model=List[AttemptHistoryOut],
    summary="Get my attempt history",
    description=(
        "Returns the authenticated user's own attempt history, ordered by most recent first. "
        "Each entry includes the `mode` (PRACTICE / EXAM) and `scope` (FULL / PART) of the attempt."
    ),
    responses={
        200: {"description": "Attempt history returned successfully."},
        **_401,
    },
)
async def my_attempt_history(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await AttemptService.user_history(
        db, user_id=current_user.id, skip=skip, limit=limit
    )


@router.get(
    "/attempts/progress",
    response_model=ProgressOut,
    summary="Get my progress over time",
    description=(
        "Returns a full progress report across all completed attempts:\n\n"
        "- **band_trend** — band score per attempt over time, including mode and scope\n"
        "- **overall_type_accuracy** — cumulative accuracy per question type\n"
        "- **top_weak_types** — up to 3 question types with accuracy below 60%\n"
        "- **type_trends** — per-question-type accuracy trend over time\n\n"
        "**Requires authentication.**"
    ),
    responses={
        200: {"description": "Progress report returned successfully."},
        **_401,
    },
)
async def my_progress(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await ProgressService.get_progress(db, user_id=current_user.id)


@router.get(
    "/attempts/{attempt_id}/result",
    response_model=AttemptResultOut,
    summary="Get an attempt result",
    description=(
        "Returns the full graded result for a completed attempt, including a per-question "
        "breakdown with correct answers and explanations.\n\n"
        "- **USER** — can only view their own attempts.\n"
        "- **ADMIN / TEACHER** — can view any user's attempt."
    ),
    responses={
        200: {"description": "Attempt result returned successfully."},
        **_401,
        **_403,
        **_404,
    },
)
async def get_result(
    attempt_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user_role_names = {r.name.upper() for r in (current_user.roles or [])}
    role = (
        UserRoleEnum.ADMIN
        if user_role_names & {"ADMIN", "TEACHER"}
        else UserRoleEnum.USER
    )
    return await AttemptService.get_result(
        db, attempt_id=attempt_id, user_id=current_user.id, role=role
    )


@router.get(
    "/attempts/{attempt_id}/analysis",
    response_model=AttemptAnalysisOut,
    summary="Get an attempt analysis",
    description=(
        "Returns a detailed analysis for a completed attempt:\n\n"
        "- **question_type_breakdown** — correct / incorrect / unanswered counts and accuracy per question type\n"
        "- **part_breakdown** — same statistics broken down per passage (Part 1 / 2 / 3)\n"
        "- **weak_question_types** — question types where accuracy fell below 60%\n"
        "- **per_question_detail** — per-question data: type, passage, status, correct answer, "
        "explanation, and the relevant passage excerpt\n"
        "- **avg_time_per_question_sec** — average time spent per question\n\n"
        "The analysis is generated automatically when the attempt is submitted. "
        "**USER** can only view their own attempts; **ADMIN / TEACHER** can view any attempt."
    ),
    responses={
        200: {"description": "Analysis returned successfully."},
        **_400,
        **_401,
        **_403,
        **_404,
    },
)
async def get_analysis(
    attempt_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user_role_names = {r.name.upper() for r in (current_user.roles or [])}
    role = (
        UserRoleEnum.ADMIN
        if user_role_names & {"ADMIN", "TEACHER"}
        else UserRoleEnum.USER
    )
    return await AnalysisService.get_analysis(
        db, attempt_id=attempt_id, user_id=current_user.id, role=role
    )


# ─────────────────────────────────────────────────────────────────────
# Admin endpoints  →  /ielts/reading/admin/...
# ─────────────────────────────────────────────────────────────────────


@router.post(
    "/admin/tests",
    response_model=ReadingTestOut,
    status_code=status.HTTP_201_CREATED,
    summary="[Admin | Teacher] Create a test",
    description=(
        "Creates a complete reading test — including all parts, question groups, "
        "sub-questions, and answer options — in a single database transaction.\n\n"
        "Set `is_free=true` to make the test visible to FREE-tier users. "
        "Populate `question_types` with every question type present in the test; "
        "this array is used for filtering on the list endpoint.\n\n"
        "**Requires ADMIN or TEACHER role.**"
    ),
    dependencies=[Depends(require_roles("ADMIN"))],
    responses={
        201: {"description": "Test created successfully."},
        **_400,
        **_401,
        **_403,
        **_422,
    },
)
async def create_test(payload: ReadingTestCreate, db: AsyncSession = Depends(get_db)):
    try:
        return await ReadingTestService.create_test(db, payload)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.delete(
    "/admin/tests/{test_id}",
    response_model=SuccessResponse,
    summary="[Admin] Soft-delete a test",
    description=(
        "Marks a test as inactive (`is_active=false`). "
        "The record is retained in the database and can be restored manually.\n\n"
        "**Requires ADMIN role.**"
    ),
    dependencies=[Depends(require_roles("ADMIN"))],
    responses={
        200: {"description": "Test deactivated successfully."},
        **_400,
        **_401,
        **_403,
        **_404,
    },
)
async def delete_test(test_id: str, db: AsyncSession = Depends(get_db)):
    try:
        await ReadingTestService.delete_test(db, test_id)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(e))
    return SuccessResponse(message="Test deactivated successfully.")


@router.get(
    "/admin/attempts",
    response_model=List[AttemptHistoryOut],
    summary="[Admin | Teacher] List all attempts",
    description=(
        "Returns a paginated list of attempts across all users, ordered by most recent first. "
        "Optionally filter by a specific `user_id`.\n\n"
        "**Requires ADMIN or TEACHER role.**"
    ),
    dependencies=[Depends(require_roles("ADMIN"))],
    responses={
        200: {"description": "Paginated attempt list returned successfully."},
        **_401,
        **_403,
    },
)
async def all_attempts(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    user_id: Optional[UUID] = Query(None, description="Filter attempts by user ID."),
    db: AsyncSession = Depends(get_db),
):
    return await AttemptService.all_history(
        db, filter_user_id=user_id, skip=skip, limit=limit
    )


@router.get(
    "/admin/attempts/{attempt_id}/analysis",
    response_model=AttemptAnalysisOut,
    summary="[Admin | Teacher] Get any attempt's analysis",
    description=(
        "Returns the full analysis for any user's attempt by ID. "
        "No ownership check is applied.\n\n"
        "**Requires ADMIN or TEACHER role.**"
    ),
    dependencies=[Depends(require_roles("ADMIN"))],
    responses={
        200: {"description": "Analysis returned successfully."},
        **_400,
        **_401,
        **_403,
        **_404,
    },
)
async def admin_get_analysis(
    attempt_id: int,
    db: AsyncSession = Depends(get_db),
):
    return await AnalysisService.get_analysis(
        db,
        attempt_id=attempt_id,
        user_id=UUID(int=0),  # placeholder — privileged path, ownership is not checked
        role=UserRoleEnum.ADMIN,
    )
