# app/modules/notifications/schemas.py
import uuid
from datetime import datetime
from typing import Optional, Any
from pydantic import BaseModel

from app.modules.notifications.models import NotificationType


class NotificationOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    type: NotificationType
    title: str
    message: str
    data: Optional[dict]
    is_read: bool
    read_at: Optional[datetime]
    expires_at: Optional[datetime]
    created_at: datetime

    model_config = {"from_attributes": True}


class NotificationCreate(BaseModel):
    """Service ichida notification yaratish uchun."""

    user_id: uuid.UUID
    type: NotificationType = NotificationType.INFO
    title: str
    message: str
    data: Optional[dict] = None
    expires_at: Optional[datetime] = None


class NotificationSettingOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    email_enabled: bool
    telegram_enabled: bool
    sms_enabled: bool
    push_enabled: bool
    payment_notifications: bool
    subscription_notifications: bool
    security_notifications: bool
    marketing_notifications: bool
    updated_at: datetime

    model_config = {"from_attributes": True}


class NotificationSettingUpdate(BaseModel):
    email_enabled: Optional[bool] = None
    telegram_enabled: Optional[bool] = None
    sms_enabled: Optional[bool] = None
    push_enabled: Optional[bool] = None
    payment_notifications: Optional[bool] = None
    subscription_notifications: Optional[bool] = None
    security_notifications: Optional[bool] = None
    marketing_notifications: Optional[bool] = None


class PaginatedNotifications(BaseModel):
    items: list[NotificationOut]
    total: int
    page: int
    size: int
    pages: int
    unread_count: int


class UnreadCount(BaseModel):
    count: int


class AdminNotificationStats(BaseModel):
    total: int
    unread: int
    by_type: dict[str, int]
    last_24h: int


class BroadcastResponse(BaseModel):
    sent: int
    message: str


class DeleteCountResponse(BaseModel):
    deleted: int
    message: str


class MarkAllResponse(BaseModel):
    marked: int
    message: str
