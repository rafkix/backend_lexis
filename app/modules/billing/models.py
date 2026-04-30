# app/modules/billing/models.py
import uuid
import enum
from datetime import datetime

from sqlalchemy import (
    Column,
    String,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Float,
    Text,
    Enum,
    JSON,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.core.database import Base, UUIDType


# ─── Enums ────────────────────────────────────────────────────────────────────
class PlanInterval(str, enum.Enum):
    MONTHLY = "monthly"
    YEARLY = "yearly"
    LIFETIME = "lifetime"


class SubscriptionStatus(str, enum.Enum):
    TRIAL = "trial"
    ACTIVE = "active"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    PAUSED = "paused"


class PaymentStatus(str, enum.Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    REFUNDED = "refunded"
    CANCELLED = "cancelled"


class PaymentProvider(str, enum.Enum):
    CLICK = "click"
    PAYME = "payme"
    UZUM = "uzum"
    STRIPE = "stripe"
    MANUAL = "manual"


class SubscriptionRequestStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class DiscountType(str, enum.Enum):
    FIXED = "fixed"  # Belgilangan miqdor chegirmasi (masalan 50 000 UZS)
    PERCENT = "percent"  # Foiz chegirmasi (masalan 20%)


# ─── Models ───────────────────────────────────────────────────────────────────
class Plan(Base):
    __tablename__ = "plans"

    id = Column(UUIDType, primary_key=True, default=uuid.uuid4)
    name = Column(String(100), nullable=False)
    slug = Column(String(100), unique=True, nullable=False)
    description = Column(Text, nullable=True)
    price = Column(Float, nullable=False, default=0.0)
    currency = Column(String(10), nullable=False, default="UZS")
    interval = Column(Enum(PlanInterval), nullable=False, default=PlanInterval.MONTHLY)
    interval_count = Column(Integer, nullable=False, default=1)
    trial_days = Column(Integer, nullable=False, default=0)
    features = Column(JSON, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    is_featured = Column(Boolean, nullable=False, default=False)
    sort_order = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    subscriptions = relationship("Subscription", back_populates="plan")
    subscription_requests = relationship("SubscriptionRequest", back_populates="plan")


class Subscription(Base):
    __tablename__ = "subscriptions"

    id = Column(UUIDType, primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUIDType, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    plan_id = Column(UUIDType, ForeignKey("plans.id"), nullable=False)
    status = Column(
        Enum(SubscriptionStatus), nullable=False, default=SubscriptionStatus.ACTIVE
    )
    start_date = Column(DateTime, nullable=False, default=datetime.utcnow)
    end_date = Column(DateTime, nullable=True)
    trial_end_date = Column(DateTime, nullable=True)
    cancelled_at = Column(DateTime, nullable=True)
    cancel_reason = Column(String(500), nullable=True)
    auto_renew = Column(Boolean, nullable=False, default=True)
    meta = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    user = relationship("User", back_populates="subscriptions")
    plan = relationship("Plan", back_populates="subscriptions")
    payments = relationship("Payment", back_populates="subscription")


class Payment(Base):
    __tablename__ = "payments"

    id = Column(UUIDType, primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUIDType, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    subscription_id = Column(UUIDType, ForeignKey("subscriptions.id"), nullable=True)
    plan_id = Column(UUIDType, ForeignKey("plans.id"), nullable=True)
    amount = Column(Float, nullable=False)
    currency = Column(String(10), nullable=False, default="UZS")
    status = Column(Enum(PaymentStatus), nullable=False, default=PaymentStatus.PENDING)
    provider = Column(
        Enum(PaymentProvider), nullable=False, default=PaymentProvider.MANUAL
    )
    provider_payment_id = Column(String(255), nullable=True, index=True)
    provider_data = Column(JSON, nullable=True)
    description = Column(Text, nullable=True)
    paid_at = Column(DateTime, nullable=True)
    refunded_at = Column(DateTime, nullable=True)
    # Promo code chegirmasi
    promo_code_id = Column(UUIDType, ForeignKey("promo_codes.id"), nullable=True)
    discount_amount = Column(Float, nullable=False, default=0.0)
    original_amount = Column(Float, nullable=True)  # chegirmadan oldingi narx
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    user = relationship("User", back_populates="payments")
    subscription = relationship("Subscription", back_populates="payments")
    plan = relationship("Plan")
    promo_code = relationship("PromoCode", back_populates="payments")


class SubscriptionRequest(Base):
    """
    User selects a plan, uploads a payment screenshot,
    and waits for admin to approve/reject.
    On approval a real Subscription + Payment are created automatically.
    """

    __tablename__ = "subscription_requests"

    id = Column(UUIDType, primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUIDType, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    plan_id = Column(UUIDType, ForeignKey("plans.id"), nullable=False)
    screenshot_url = Column(String(500), nullable=False)
    note = Column(Text, nullable=True)
    status = Column(
        Enum(SubscriptionRequestStatus),
        nullable=False,
        default=SubscriptionRequestStatus.PENDING,
    )
    # Promo code (ixtiyoriy)
    promo_code_id = Column(UUIDType, ForeignKey("promo_codes.id"), nullable=True)
    discount_amount = Column(Float, nullable=False, default=0.0)
    original_amount = Column(Float, nullable=True)

    # Admin fields
    reviewed_by = Column(UUIDType, ForeignKey("users.id"), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    rejection_reason = Column(String(500), nullable=True)
    subscription_id = Column(UUIDType, ForeignKey("subscriptions.id"), nullable=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    user = relationship(
        "User", foreign_keys=[user_id], back_populates="subscription_requests"
    )
    reviewer = relationship("User", foreign_keys=[reviewed_by])
    plan = relationship("Plan", back_populates="subscription_requests")
    subscription = relationship("Subscription")
    promo_code = relationship("PromoCode", back_populates="subscription_requests")


# ─── PromoCode ────────────────────────────────────────────────────────────────
class PromoCode(Base):
    """
    Promo kodlar: foiz yoki belgilangan miqdor chegirma beradi.
    Admin tomonidan yaratiladi, user subscribe/request paytida ishlatadi.
    """

    __tablename__ = "promo_codes"

    id = Column(UUIDType, primary_key=True, default=uuid.uuid4)
    code = Column(String(50), unique=True, nullable=False, index=True)
    description = Column(Text, nullable=True)

    discount_type = Column(
        Enum(DiscountType), nullable=False, default=DiscountType.PERCENT
    )
    # PERCENT → 0–100 qiymat, FIXED → UZS miqdori
    discount_value = Column(Float, nullable=False)

    # Qaysi planlarga tegishli (NULL = barcha planlarga)
    plan_id = Column(UUIDType, ForeignKey("plans.id"), nullable=True)

    # Foydalanish limiti (NULL = cheksiz)
    max_uses = Column(Integer, nullable=True)
    uses_count = Column(Integer, nullable=False, default=0)

    # Bir foydalanuvchi bir marta ishlatishi (True bo'lsa)
    one_per_user = Column(Boolean, nullable=False, default=True)

    # Amal qilish muddati
    valid_from = Column(DateTime, nullable=False, default=datetime.utcnow)
    valid_until = Column(DateTime, nullable=True)

    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    plan = relationship("Plan")
    usages = relationship("PromoCodeUsage", back_populates="promo_code")
    payments = relationship("Payment", back_populates="promo_code")
    subscription_requests = relationship(
        "SubscriptionRequest", back_populates="promo_code"
    )


class PromoCodeUsage(Base):
    """
    Har bir foydalanuvchi promo kodni ishlatganini track qiladi.
    """

    __tablename__ = "promo_code_usages"
    __table_args__ = (
        UniqueConstraint("promo_code_id", "user_id", name="uq_promo_user"),
    )

    id = Column(UUIDType, primary_key=True, default=uuid.uuid4)
    promo_code_id = Column(
        UUIDType, ForeignKey("promo_codes.id", ondelete="CASCADE"), nullable=False
    )
    user_id = Column(
        UUIDType, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # Qaysi payment yoki request orqali ishlatilgan
    payment_id = Column(UUIDType, ForeignKey("payments.id"), nullable=True)
    subscription_request_id = Column(
        UUIDType, ForeignKey("subscription_requests.id"), nullable=True
    )
    discount_amount = Column(Float, nullable=False, default=0.0)
    used_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    promo_code = relationship("PromoCode", back_populates="usages")
