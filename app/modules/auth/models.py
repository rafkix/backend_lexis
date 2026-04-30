import uuid
import enum
import secrets
from datetime import datetime, timezone

from sqlalchemy import (
    Enum as SAEnum,
    String,
    ForeignKey,
    Table,
    Column,
    UniqueConstraint,
    Index,
    Boolean,
    DateTime,
    Integer,
    JSON,
)
from sqlalchemy.types import (
    Uuid as UuidType,
)  # ✅ SQLite + PostgreSQL ikkisida ham ishlaydi
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


# =====================================================
# 🔧 UTILS
# =====================================================


def generate_public_id() -> str:
    return str(secrets.randbelow(90000000) + 10000000)


# =====================================================
# 📌 ENUMS
# =====================================================


class UserStatus(str, enum.Enum):
    PENDING = "pending"
    ACTIVE = "active"
    BLOCKED = "blocked"


class AuthProvider(str, enum.Enum):
    EMAIL = "email"
    GOOGLE = "google"
    TELEGRAM = "telegram"


class AuthAction(str, enum.Enum):
    LOGIN = "login"
    LOGOUT = "logout"
    REGISTER = "register"
    REFRESH = "refresh"
    PASSWORD_CHANGE = "password_change"


# =====================================================
# ⏱ MIXIN
# =====================================================


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


# =====================================================
# 👑 ROLE
# =====================================================


class Role(Base, TimestampMixin):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(String(255))

    users: Mapped[list["User"]] = relationship(
        secondary="user_roles", back_populates="roles"
    )


# =====================================================
# 🔗 USER-ROLE
# =====================================================

user_roles = Table(
    "user_roles",
    Base.metadata,
    Column("user_id", UuidType, ForeignKey("users.id", ondelete="CASCADE")),
    Column("role_id", Integer, ForeignKey("roles.id", ondelete="CASCADE")),
    UniqueConstraint("user_id", "role_id"),
)


# =====================================================
# 👤 USER
# =====================================================


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UuidType, primary_key=True, default=uuid.uuid4
    )
    public_id: Mapped[str] = mapped_column(
        String(16), unique=True, index=True, default=generate_public_id
    )

    # AUTH
    email: Mapped[str | None] = mapped_column(String(255), unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(50), unique=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(20), unique=True, index=True)
    password_hash: Mapped[str | None] = mapped_column(String(255))

    # PROFILE
    full_name: Mapped[str | None] = mapped_column(String(255))
    avatar: Mapped[str | None] = mapped_column(String(500))
    telegram_id: Mapped[str | None] = mapped_column(String(50), unique=True, index=True)
    google_id: Mapped[str | None] = mapped_column(String(255), unique=True, index=True)

    # STATUS
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    phone_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[UserStatus] = mapped_column(
        SAEnum(UserStatus), default=UserStatus.ACTIVE
    )

    # SUBSCRIPTION TIER
    # FREE → tekin testlar; PREMIUM → barcha testlar; PRO → EXAM mode
    subscription_tier: Mapped[str] = mapped_column(
        String(20), nullable=False, default="FREE", index=True
    )
    subscription_tier_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # META
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    meta: Mapped[dict] = mapped_column(JSON, default=dict)

    # RELATIONS
    roles: Mapped[list["Role"]] = relationship(
        secondary="user_roles",
        lazy="selectin",
        back_populates="users",
    )
    sessions: Mapped[list["Session"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    accounts: Mapped[list["SocialAccount"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    devices: Mapped[list["Device"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    subscriptions = relationship(
        "Subscription", back_populates="user", cascade="all, delete-orphan"
    )

    payments = relationship(
        "Payment", back_populates="user", cascade="all, delete-orphan"
    )

    notifications = relationship(
        "Notification", back_populates="user", cascade="all, delete-orphan"
    )

    notification_settings = relationship(
        "NotificationSetting",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )
    subscription_requests = relationship(
        "SubscriptionRequest",
        foreign_keys="SubscriptionRequest.user_id",  # 👈 REQUIRED
        back_populates="user",
    )
    test_attempts = relationship("UserTestAttempt", back_populates="user")


# =====================================================
# 📱 DEVICE
# =====================================================


class Device(Base, TimestampMixin):
    __tablename__ = "devices"

    id: Mapped[uuid.UUID] = mapped_column(
        UuidType, primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )
    fingerprint: Mapped[str] = mapped_column(String(255), index=True)
    user_agent: Mapped[str | None] = mapped_column(String(500))
    ip_address: Mapped[str | None] = mapped_column(String(50))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped["User"] = relationship(back_populates="devices")


# =====================================================
# 🔐 SESSION
# =====================================================


class Session(Base, TimestampMixin):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UuidType, primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    refresh_token_jti: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    refresh_token_hash: Mapped[str] = mapped_column(String(255))
    is_revoked: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ip_address: Mapped[str | None] = mapped_column(String(50))
    user_agent: Mapped[str | None] = mapped_column(String(500))

    user: Mapped["User"] = relationship(back_populates="sessions")


# =====================================================
# 🌐 SOCIAL ACCOUNT
# =====================================================


class SocialAccount(Base, TimestampMixin):
    __tablename__ = "social_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )
    provider: Mapped[AuthProvider] = mapped_column(SAEnum(AuthProvider))
    provider_id: Mapped[str] = mapped_column(String(255), index=True)
    email: Mapped[str | None] = mapped_column(String(255))
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)

    user: Mapped["User"] = relationship(back_populates="accounts")

    __table_args__ = (UniqueConstraint("provider", "provider_id"),)


# =====================================================
# 📊 AUTH LOG
# =====================================================


class AuthLog(Base):
    __tablename__ = "auth_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UuidType, nullable=True, index=True
    )
    action: Mapped[AuthAction] = mapped_column(SAEnum(AuthAction))
    ip_address: Mapped[str | None] = mapped_column(String(50))
    user_agent: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(50))
    error_message: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )


# =====================================================
# 📞 PHONE VERIFICATION
# =====================================================


class PhoneVerification(Base):
    __tablename__ = "phone_verifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    phone: Mapped[str] = mapped_column(String(20), index=True)
    code_hash: Mapped[str] = mapped_column(String(255))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    is_used: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    attempts: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )

    __table_args__ = (
        Index("ix_phone_verification_lookup", "user_id", "phone", "is_used"),
    )


# =====================================================
# 🔑 PASSWORD RESET TOKEN
# =====================================================


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    is_used: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    @staticmethod
    def generate_token() -> str:
        return secrets.token_urlsafe(64)

    @property
    def is_expired(self) -> bool:
        return datetime.now(timezone.utc) > self.expires_at
