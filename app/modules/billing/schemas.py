# app/modules/billing/schemas.py
import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field

from app.modules.billing.models import (
    PlanInterval,
    SubscriptionStatus,
    SubscriptionRequestStatus,
    PaymentStatus,
    PaymentProvider,
    DiscountType,
)


# ─── Plan ─────────────────────────────────────────────────────────────────────
class PlanOut(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    description: Optional[str]
    price: float
    currency: str
    interval: PlanInterval
    interval_count: int
    trial_days: int
    features: Optional[dict]
    is_active: bool
    is_featured: bool
    sort_order: int
    created_at: datetime

    model_config = {"from_attributes": True}


class PlanCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    slug: str = Field(..., min_length=2, max_length=100)
    description: Optional[str] = None
    price: float = Field(..., ge=0)
    currency: str = Field("UZS", max_length=10)
    interval: PlanInterval = PlanInterval.MONTHLY
    interval_count: int = Field(1, ge=1)
    trial_days: int = Field(0, ge=0)
    features: Optional[dict] = None
    is_active: bool = True
    is_featured: bool = False
    sort_order: int = 0


class PlanUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    price: Optional[float] = None
    features: Optional[dict] = None
    is_active: Optional[bool] = None
    is_featured: Optional[bool] = None
    sort_order: Optional[int] = None


# ─── Subscription ─────────────────────────────────────────────────────────────
class SubscriptionOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    plan_id: uuid.UUID
    plan: PlanOut
    status: SubscriptionStatus
    start_date: datetime
    end_date: Optional[datetime]
    trial_end_date: Optional[datetime]
    cancelled_at: Optional[datetime]
    cancel_reason: Optional[str]
    auto_renew: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class SubscribeRequest(BaseModel):
    plan_slug: str
    auto_renew: bool = True
    provider: PaymentProvider = PaymentProvider.MANUAL
    promo_code: Optional[str] = Field(
        None, max_length=50, description="Promo kod (ixtiyoriy)"
    )


class CancelRequest(BaseModel):
    reason: Optional[str] = Field(None, max_length=500)


# ─── PromoCode ────────────────────────────────────────────────────────────────
class PromoCodeOut(BaseModel):
    id: uuid.UUID
    code: str
    description: Optional[str]
    discount_type: DiscountType
    discount_value: float
    plan_id: Optional[uuid.UUID]
    max_uses: Optional[int]
    uses_count: int
    one_per_user: bool
    valid_from: datetime
    valid_until: Optional[datetime]
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class PromoCodeCreate(BaseModel):
    code: str = Field(..., min_length=3, max_length=50)
    description: Optional[str] = None
    discount_type: DiscountType = DiscountType.PERCENT
    discount_value: float = Field(..., gt=0)
    plan_id: Optional[uuid.UUID] = Field(
        None, description="Faqat shu plan uchun (NULL = barcha planlar)"
    )
    max_uses: Optional[int] = Field(None, ge=1, description="Maksimal foydalanish soni")
    one_per_user: bool = True
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None
    is_active: bool = True


class PromoCodeUpdate(BaseModel):
    description: Optional[str] = None
    discount_value: Optional[float] = Field(None, gt=0)
    max_uses: Optional[int] = Field(None, ge=1)
    one_per_user: Optional[bool] = None
    valid_until: Optional[datetime] = None
    is_active: Optional[bool] = None


class PromoCodeValidateRequest(BaseModel):
    """Foydalanuvchi promo kodni tekshiradi (plan_slug bilan)."""

    code: str
    plan_slug: str


class PromoCodeValidateOut(BaseModel):
    """Tekshirish natijasi: chegirma miqdori va final narx."""

    valid: bool
    code: str
    discount_type: DiscountType
    discount_value: float
    original_price: float
    discount_amount: float
    final_price: float
    message: Optional[str] = None


class PaginatedPromoCodes(BaseModel):
    items: list[PromoCodeOut]
    total: int
    page: int
    size: int
    pages: int


# ─── Subscription Request (manual screenshot flow) ────────────────────────────
class SubscriptionRequestOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    plan_id: uuid.UUID
    plan: PlanOut
    screenshot_url: str
    note: Optional[str]
    status: SubscriptionRequestStatus
    promo_code_id: Optional[uuid.UUID]
    discount_amount: float
    original_amount: Optional[float]
    reviewed_by: Optional[uuid.UUID]
    reviewed_at: Optional[datetime]
    rejection_reason: Optional[str]
    subscription_id: Optional[uuid.UUID]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SubscriptionRequestCreate(BaseModel):
    """User submits: plan slug + screenshot URL + optional note + optional promo."""

    plan_slug: str
    screenshot_url: str = Field(..., min_length=5, max_length=500)
    note: Optional[str] = Field(None, max_length=1000)
    promo_code: Optional[str] = Field(
        None, max_length=50, description="Promo kod (ixtiyoriy)"
    )


class SubscriptionRequestReview(BaseModel):
    """Admin approves or rejects."""

    action: str = Field(..., pattern="^(approve|reject)$")
    rejection_reason: Optional[str] = Field(None, max_length=500)


class PaginatedSubscriptionRequests(BaseModel):
    items: list[SubscriptionRequestOut]
    total: int
    page: int
    size: int
    pages: int


# ─── Payment ──────────────────────────────────────────────────────────────────
class PaymentOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    subscription_id: Optional[uuid.UUID]
    plan_id: Optional[uuid.UUID]
    amount: float
    currency: str
    status: PaymentStatus
    provider: PaymentProvider
    provider_payment_id: Optional[str]
    description: Optional[str]
    promo_code_id: Optional[uuid.UUID]
    discount_amount: float
    original_amount: Optional[float]
    paid_at: Optional[datetime]
    refunded_at: Optional[datetime]
    created_at: datetime

    model_config = {"from_attributes": True}


class ManualPaymentCreate(BaseModel):
    """Admin: create payment manually."""

    user_id: uuid.UUID
    plan_slug: str
    amount: float
    currency: str = "UZS"
    description: Optional[str] = None
    provider: PaymentProvider = PaymentProvider.MANUAL


# ─── Paginated responses ──────────────────────────────────────────────────────
class PaginatedPayments(BaseModel):
    items: list[PaymentOut]
    total: int
    page: int
    size: int
    pages: int


class PaginatedPlans(BaseModel):
    items: list[PlanOut]
    total: int
