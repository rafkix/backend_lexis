# app/modules/billing/router.py
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query, HTTPException, status
from app.modules.auth.dependencies import get_current_user, require_roles
from app.modules.auth.models import User
from app.modules.billing.dependencies import get_billing_service
from app.modules.billing.service import BillingService
from app.modules.billing.schemas import (
    PlanOut,
    PlanCreate,
    PlanUpdate,
    SubscriptionOut,
    SubscribeRequest,
    CancelRequest,
    SubscriptionRequestOut,
    SubscriptionRequestCreate,
    SubscriptionRequestReview,
    PaginatedSubscriptionRequests,
    PaymentOut,
    PaginatedPayments,
    ManualPaymentCreate,
    PromoCodeOut,
    PromoCodeCreate,
    PromoCodeUpdate,
    PromoCodeValidateRequest,
    PromoCodeValidateOut,
    PaginatedPromoCodes,
)
from app.modules.billing.models import PaymentStatus, SubscriptionRequestStatus

# ─── Shared response doc blocks ───────────────────────────────────────────────

_400 = {400: {"description": "Bad request — invalid input or business rule violation."}}
_401 = {401: {"description": "Not authenticated — Bearer token missing or invalid."}}
_403 = {403: {"description": "Forbidden — admin role required."}}
_404 = {404: {"description": "Not found — the requested resource does not exist."}}
_422 = {
    422: {
        "description": "Validation error — request body or query params are malformed."
    }
}

_auth = {**_401}
_admin = {**_401, **_403}
_crud = {**_400, **_401, **_403, **_404}

_admin_deps = [Depends(require_roles("ADMIN"))]

# ══════════════════════════════════════════════════════════════════════
# Single router  →  /billing/...
# ══════════════════════════════════════════════════════════════════════

router = APIRouter(prefix="/billing", tags=["Billing"])


# ─────────────────────────────────────────────────────────────────────
# PLANS — Public
# ─────────────────────────────────────────────────────────────────────


@router.get(
    "/plans",
    response_model=list[PlanOut],
    summary="List active plans",
    description="Returns all publicly available (active) subscription plans. No authentication required.",
    responses={
        200: {"description": "List of active plans returned successfully."},
    },
)
async def list_plans(
    service: BillingService = Depends(get_billing_service),
):
    return await service.get_plans(only_active=True)


@router.get(
    "/plans/{slug}",
    response_model=PlanOut,
    summary="Get plan by slug",
    description="Returns a single active plan by its unique slug. No authentication required.",
    responses={
        200: {"description": "Plan returned successfully."},
        **_404,
    },
)
async def get_plan(
    slug: str,
    service: BillingService = Depends(get_billing_service),
):
    plan = await service.get_plan_by_slug(slug)
    if not plan:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Plan not found.")
    return plan


# ─────────────────────────────────────────────────────────────────────
# PLANS — Admin
# ─────────────────────────────────────────────────────────────────────


@router.post(
    "/admin/plans",
    response_model=PlanOut,
    status_code=status.HTTP_201_CREATED,
    summary="[Admin] Create a plan",
    description="Creates a new subscription plan. Slug must be unique. **Requires admin role.**",
    dependencies=_admin_deps,
    responses={
        201: {"description": "Plan created successfully."},
        **_400,
        **_admin,
        **_422,
    },
)
async def create_plan(
    data: PlanCreate,
    service: BillingService = Depends(get_billing_service),
):
    try:
        return await service.create_plan(data)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.patch(
    "/admin/plans/{plan_id}",
    response_model=PlanOut,
    summary="[Admin] Update a plan",
    description="Partially updates a subscription plan by ID. Only provided fields are changed. **Requires admin role.**",
    dependencies=_admin_deps,
    responses={
        200: {"description": "Plan updated successfully."},
        **_crud,
        **_422,
    },
)
async def update_plan(
    plan_id: uuid.UUID,
    data: PlanUpdate,
    service: BillingService = Depends(get_billing_service),
):
    try:
        return await service.update_plan(plan_id, data)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.delete(
    "/admin/plans/{plan_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="[Admin] Delete a plan",
    description="Deletes a subscription plan by ID. Plans with active subscribers cannot be deleted. **Requires admin role.**",
    dependencies=_admin_deps,
    responses={
        204: {"description": "Plan deleted successfully. No content returned."},
        **_400,
        **_admin,
        **_404,
    },
)
async def delete_plan(
    plan_id: uuid.UUID,
    service: BillingService = Depends(get_billing_service),
):
    try:
        await service.delete_plan(plan_id)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(e))


# ─────────────────────────────────────────────────────────────────────
# PROMO CODES — Public (validate only)
# ─────────────────────────────────────────────────────────────────────


@router.post(
    "/promo-codes/validate",
    response_model=PromoCodeValidateOut,
    summary="Validate a promo code",
    description=(
        "Checks whether a promo code is valid for the given plan. "
        "Returns the discount amount and final price. "
        "The promo code is **not consumed** at this step — it is applied only on subscribe. "
        "Authentication required."
    ),
    responses={
        200: {"description": "Promo code is valid. Discount details returned."},
        **_400,
        **_auth,
        **_422,
    },
)
async def validate_promo_code(
    data: PromoCodeValidateRequest,
    user: User = Depends(get_current_user),
    service: BillingService = Depends(get_billing_service),
):
    try:
        return await service.validate_promo_code(data.code, data.plan_slug, user.id)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(e))


# ─────────────────────────────────────────────────────────────────────
# PROMO CODES — Admin (CRUD)
# ─────────────────────────────────────────────────────────────────────


@router.get(
    "/admin/promo-codes",
    response_model=PaginatedPromoCodes,
    summary="[Admin] List promo codes",
    description="Returns a paginated list of all promo codes. Filter by active status. **Requires admin role.**",
    dependencies=_admin_deps,
    responses={
        200: {"description": "Paginated promo code list returned successfully."},
        **_admin,
    },
)
async def list_promo_codes(
    page: int = Query(1, ge=1, description="Page number"),
    size: int = Query(20, ge=1, le=100, description="Items per page (max 100)"),
    only_active: bool = Query(False, description="Return only active promo codes"),
    service: BillingService = Depends(get_billing_service),
):
    return await service.list_promo_codes(page, size, only_active)


@router.get(
    "/admin/promo-codes/{promo_id}",
    response_model=PromoCodeOut,
    summary="[Admin] Get promo code by ID",
    description="Returns a single promo code by its UUID. **Requires admin role.**",
    dependencies=_admin_deps,
    responses={
        200: {"description": "Promo code returned successfully."},
        **_admin,
        **_404,
    },
)
async def get_promo_code(
    promo_id: uuid.UUID,
    service: BillingService = Depends(get_billing_service),
):
    promo = await service.get_promo_code_by_id(promo_id)
    if not promo:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Promo code not found.")
    return promo


@router.post(
    "/admin/promo-codes",
    response_model=PromoCodeOut,
    status_code=status.HTTP_201_CREATED,
    summary="[Admin] Create a promo code",
    description="Creates a new promo code with discount rules and optional expiry. Code must be unique. **Requires admin role.**",
    dependencies=_admin_deps,
    responses={
        201: {"description": "Promo code created successfully."},
        **_400,
        **_admin,
        **_422,
    },
)
async def create_promo_code(
    data: PromoCodeCreate,
    service: BillingService = Depends(get_billing_service),
):
    try:
        return await service.create_promo_code(data)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.patch(
    "/admin/promo-codes/{promo_id}",
    response_model=PromoCodeOut,
    summary="[Admin] Update a promo code",
    description="Partially updates a promo code by ID. **Requires admin role.**",
    dependencies=_admin_deps,
    responses={
        200: {"description": "Promo code updated successfully."},
        **_crud,
        **_422,
    },
)
async def update_promo_code(
    promo_id: uuid.UUID,
    data: PromoCodeUpdate,
    service: BillingService = Depends(get_billing_service),
):
    try:
        return await service.update_promo_code(promo_id, data)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.delete(
    "/admin/promo-codes/{promo_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="[Admin] Delete a promo code",
    description="Permanently deletes a promo code by ID. **Requires admin role.**",
    dependencies=_admin_deps,
    responses={
        204: {"description": "Promo code deleted. No content returned."},
        **_400,
        **_admin,
        **_404,
    },
)
async def delete_promo_code(
    promo_id: uuid.UUID,
    service: BillingService = Depends(get_billing_service),
):
    try:
        await service.delete_promo_code(promo_id)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(e))


# ─────────────────────────────────────────────────────────────────────
# SUBSCRIPTIONS — Auth
# ─────────────────────────────────────────────────────────────────────


@router.get(
    "/subscription",
    response_model=Optional[SubscriptionOut],
    summary="Get my active subscription",
    description="Returns the authenticated user's current active subscription, or `null` if none exists.",
    responses={
        200: {
            "description": "Active subscription returned (or null if not subscribed)."
        },
        **_auth,
    },
)
async def my_subscription(
    user: User = Depends(get_current_user),
    service: BillingService = Depends(get_billing_service),
):
    return await service.get_active_subscription(user.id)


@router.get(
    "/subscription/history",
    response_model=list[SubscriptionOut],
    summary="Get subscription history",
    description="Returns all past and present subscriptions for the authenticated user, ordered by creation date descending.",
    responses={
        200: {"description": "Subscription history returned successfully."},
        **_auth,
    },
)
async def subscription_history(
    user: User = Depends(get_current_user),
    service: BillingService = Depends(get_billing_service),
):
    return await service.get_user_subscriptions(user.id)


@router.post(
    "/subscribe",
    response_model=SubscriptionOut,
    status_code=status.HTTP_201_CREATED,
    summary="Subscribe to a plan",
    description=(
        "Creates a new subscription for the authenticated user. "
        "Optionally include a `promo_code` in the request body to apply a discount — "
        "the code is validated and consumed at this step."
    ),
    responses={
        201: {"description": "Subscription created successfully."},
        **_400,
        **_auth,
        **_422,
    },
)
async def subscribe(
    data: SubscribeRequest,
    user: User = Depends(get_current_user),
    service: BillingService = Depends(get_billing_service),
):
    try:
        subscription, _ = await service.subscribe(user, data)
        return subscription
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post(
    "/subscription/cancel",
    response_model=SubscriptionOut,
    summary="Cancel active subscription",
    description=(
        "Cancels the authenticated user's active subscription. "
        "The subscription remains accessible until the end of the current billing period."
    ),
    responses={
        200: {"description": "Subscription cancelled successfully."},
        **_400,
        **_auth,
    },
)
async def cancel_subscription(
    data: CancelRequest,
    user: User = Depends(get_current_user),
    service: BillingService = Depends(get_billing_service),
):
    try:
        return await service.cancel_subscription(user.id, data)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(e))


# ─────────────────────────────────────────────────────────────────────
# SUBSCRIPTION REQUESTS — Screenshot / manual payment flow
# ─────────────────────────────────────────────────────────────────────


@router.post(
    "/subscription-requests",
    response_model=SubscriptionRequestOut,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a subscription request",
    description=(
        "User selects a plan and uploads a bank transfer screenshot for manual verification. "
        "Optionally include a `promo_code` — the discount is recorded on the request and "
        "applied to the payment once an admin approves it."
    ),
    responses={
        201: {
            "description": "Subscription request submitted successfully. Awaiting admin review."
        },
        **_400,
        **_auth,
        **_422,
    },
)
async def create_subscription_request(
    data: SubscriptionRequestCreate,
    user: User = Depends(get_current_user),
    service: BillingService = Depends(get_billing_service),
):
    try:
        return await service.create_subscription_request(user, data)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get(
    "/subscription-requests/my",
    response_model=PaginatedSubscriptionRequests,
    summary="List my subscription requests",
    description="Returns a paginated list of the authenticated user's own subscription requests.",
    responses={
        200: {"description": "Paginated list of user's subscription requests."},
        **_auth,
    },
)
async def my_subscription_requests(
    page: int = Query(1, ge=1, description="Page number"),
    size: int = Query(20, ge=1, le=100, description="Items per page"),
    user: User = Depends(get_current_user),
    service: BillingService = Depends(get_billing_service),
):
    return await service.get_my_requests(user.id, page, size)


@router.get(
    "/subscription-requests/{request_id}",
    response_model=SubscriptionRequestOut,
    summary="Get a subscription request",
    description=(
        "Returns a single subscription request by ID. "
        "Users can only view their own requests; admins can view any request."
    ),
    responses={
        200: {"description": "Subscription request returned successfully."},
        **_auth,
        403: {"description": "Forbidden — this request belongs to another user."},
        **_404,
    },
)
async def get_subscription_request(
    request_id: uuid.UUID,
    user: User = Depends(get_current_user),
    service: BillingService = Depends(get_billing_service),
):
    req = await service.get_request_by_id(request_id)
    if not req:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail="Subscription request not found."
        )
    if req.user_id != user.id and "admin" not in (user.roles or []):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, detail="You do not have access to this request."
        )
    return req


@router.get(
    "/admin/subscription-requests",
    response_model=PaginatedSubscriptionRequests,
    summary="[Admin] List all subscription requests",
    description="Returns a paginated list of all subscription requests across all users. Filter by status. **Requires admin role.**",
    dependencies=_admin_deps,
    responses={
        200: {"description": "Paginated list of all subscription requests."},
        **_admin,
    },
)
async def all_subscription_requests(
    page: int = Query(1, ge=1, description="Page number"),
    size: int = Query(20, ge=1, le=100, description="Items per page"),
    request_status: Optional[SubscriptionRequestStatus] = Query(
        None, alias="status", description="Filter by request status"
    ),
    service: BillingService = Depends(get_billing_service),
):
    return await service.get_all_requests(page, size, request_status)


@router.post(
    "/admin/subscription-requests/{request_id}/review",
    response_model=SubscriptionRequestOut,
    summary="[Admin] Review a subscription request",
    description=(
        "Approves or rejects a pending subscription request. "
        "On approval, the discounted payment is created and the subscription is activated. "
        "**Requires admin role.**"
    ),
    dependencies=_admin_deps,
    responses={
        200: {"description": "Request reviewed successfully."},
        **_400,
        **_admin,
        **_404,
    },
)
async def review_subscription_request(
    request_id: uuid.UUID,
    data: SubscriptionRequestReview,
    admin: User = Depends(get_current_user),
    service: BillingService = Depends(get_billing_service),
):
    try:
        return await service.review_subscription_request(request_id, admin, data)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(e))


# ─────────────────────────────────────────────────────────────────────
# PAYMENTS — Auth
# ─────────────────────────────────────────────────────────────────────


@router.get(
    "/payments",
    response_model=PaginatedPayments,
    summary="List my payments",
    description="Returns a paginated list of the authenticated user's payment history. Optionally filter by payment status.",
    responses={
        200: {"description": "Paginated payment history returned successfully."},
        **_auth,
    },
)
async def my_payments(
    page: int = Query(1, ge=1, description="Page number"),
    size: int = Query(20, ge=1, le=100, description="Items per page"),
    payment_status: Optional[PaymentStatus] = Query(
        None, alias="status", description="Filter by payment status"
    ),
    user: User = Depends(get_current_user),
    service: BillingService = Depends(get_billing_service),
):
    return await service.get_payments(user.id, page, size, payment_status)


@router.get(
    "/payments/{payment_id}",
    response_model=PaymentOut,
    summary="Get a payment by ID",
    description="Returns a single payment record. Users can only access their own payments.",
    responses={
        200: {"description": "Payment returned successfully."},
        **_auth,
        **_404,
    },
)
async def get_payment(
    payment_id: uuid.UUID,
    user: User = Depends(get_current_user),
    service: BillingService = Depends(get_billing_service),
):
    payment = await service.get_payment_by_id(payment_id, user_id=user.id)
    if not payment:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Payment not found.")
    return payment


# ─────────────────────────────────────────────────────────────────────
# PAYMENTS — Admin
# ─────────────────────────────────────────────────────────────────────


@router.post(
    "/admin/payments/manual",
    response_model=PaymentOut,
    status_code=status.HTTP_201_CREATED,
    summary="[Admin] Create a manual payment",
    description=(
        "Creates a payment record manually for a user (e.g. cash or offline transfer). "
        "**Requires admin role.**"
    ),
    dependencies=_admin_deps,
    responses={
        201: {"description": "Manual payment created successfully."},
        **_400,
        **_admin,
        **_422,
    },
)
async def manual_payment(
    data: ManualPaymentCreate,
    service: BillingService = Depends(get_billing_service),
):
    try:
        return await service.create_manual_payment(data)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post(
    "/admin/payments/{payment_id}/confirm",
    response_model=PaymentOut,
    summary="[Admin] Confirm a payment",
    description=(
        "Marks a pending payment as confirmed and activates the associated subscription. "
        "**Requires admin role.**"
    ),
    dependencies=_admin_deps,
    responses={
        200: {"description": "Payment confirmed and subscription activated."},
        **_400,
        **_admin,
        **_404,
    },
)
async def confirm_payment(
    payment_id: uuid.UUID,
    service: BillingService = Depends(get_billing_service),
):
    try:
        return await service.confirm_payment(payment_id)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(e))
