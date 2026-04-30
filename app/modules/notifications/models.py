# app/modules/notifications/models.py
import uuid
import enum
from datetime import datetime

from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Text, Enum, JSON
from sqlalchemy.orm import relationship

from app.core.database import Base, UUIDType


class NotificationType(str, enum.Enum):
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"
    PAYMENT = "payment"
    SUBSCRIPTION = "subscription"
    SECURITY = "security"
    SYSTEM = "system"


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(UUIDType, primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUIDType, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    type = Column(Enum(NotificationType), nullable=False, default=NotificationType.INFO)
    title = Column(String(255), nullable=False)
    message = Column(Text, nullable=False)
    data = Column(JSON, nullable=True)  # {"url": "/...", "action": "..."}
    is_read = Column(Boolean, nullable=False, default=False, index=True)
    read_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)

    user = relationship("User", back_populates="notifications")


class NotificationSetting(Base):
    __tablename__ = "notification_settings"

    id = Column(UUIDType, primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUIDType,
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    email_enabled = Column(Boolean, nullable=False, default=True)
    telegram_enabled = Column(Boolean, nullable=False, default=True)
    sms_enabled = Column(Boolean, nullable=False, default=False)
    push_enabled = Column(Boolean, nullable=False, default=True)
    payment_notifications = Column(Boolean, nullable=False, default=True)
    subscription_notifications = Column(Boolean, nullable=False, default=True)
    security_notifications = Column(Boolean, nullable=False, default=True)
    marketing_notifications = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    user = relationship("User", back_populates="notification_settings")
