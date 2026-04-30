# app/modules/notifications/service.py
import uuid
import math
from datetime import datetime
from typing import Optional

from sqlalchemy import select, func, and_, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.notifications.models import (
    Notification, NotificationSetting, NotificationType
)
from app.modules.notifications.schemas import (
    NotificationCreate, NotificationSettingUpdate
)


class NotificationService:
    def __init__(self, db: AsyncSession):
        self.db = db

    def _now(self) -> datetime:
        return datetime.utcnow()

    # ════════════════════════════════════════════════════════════════
    # HELPERS — boshqa service lardan chaqirish uchun
    # ════════════════════════════════════════════════════════════════

    async def send(
        self,
        user_id    : uuid.UUID,
        title      : str,
        message    : str,
        type       : NotificationType = NotificationType.INFO,
        data       : Optional[dict]   = None,
        expires_at : Optional[datetime] = None,
    ) -> Notification:
        """Istalgan joydan tez notification yuborish."""
        notification = Notification(
            user_id    = user_id,
            type       = type,
            title      = title,
            message    = message,
            data       = data,
            expires_at = expires_at,
        )
        self.db.add(notification)
        await self.db.commit()
        await self.db.refresh(notification)
        return notification

    # ════════════════════════════════════════════════════════════════
    # LIST / GET
    # ════════════════════════════════════════════════════════════════

    async def get_notifications(
        self,
        user_id  : uuid.UUID,
        page     : int = 1,
        size     : int = 20,
        unread_only: bool = False,
        type     : Optional[NotificationType] = None,
    ) -> dict:
        stmt = select(Notification).where(Notification.user_id == user_id)

        if unread_only:
            stmt = stmt.where(Notification.is_read == False)
        if type:
            stmt = stmt.where(Notification.type == type)

        # O'tmagan (expired emas) notificationlar
        stmt = stmt.where(
            (Notification.expires_at == None) |
            (Notification.expires_at > self._now())
        )

        # Umumiy son
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.db.execute(count_stmt)).scalar_one()

        # O'qilmagan sonini alohida olish
        unread_stmt = select(func.count()).where(
            Notification.user_id == user_id,
            Notification.is_read == False,
        )
        unread_count = (await self.db.execute(unread_stmt)).scalar_one()

        stmt = stmt.order_by(Notification.created_at.desc())
        stmt = stmt.offset((page - 1) * size).limit(size)
        items = (await self.db.execute(stmt)).scalars().all()

        return {
            "items"       : items,
            "total"       : total,
            "page"        : page,
            "size"        : size,
            "pages"       : math.ceil(total / size) if total else 0,
            "unread_count": unread_count,
        }

    async def get_unread_count(self, user_id: uuid.UUID) -> int:
        result = await self.db.execute(
            select(func.count()).where(
                Notification.user_id == user_id,
                Notification.is_read == False,
            )
        )
        return result.scalar_one()

    # ════════════════════════════════════════════════════════════════
    # MARK AS READ
    # ════════════════════════════════════════════════════════════════

    async def mark_as_read(
        self,
        notification_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> Notification:
        result = await self.db.execute(
            select(Notification).where(
                Notification.id == notification_id,
                Notification.user_id == user_id,
            )
        )
        notification = result.scalar_one_or_none()
        if not notification:
            raise ValueError("Notification topilmadi")

        if not notification.is_read:
            notification.is_read = True
            notification.read_at = self._now()
            await self.db.commit()
            await self.db.refresh(notification)

        return notification

    async def mark_all_as_read(self, user_id: uuid.UUID) -> int:
        """Barcha o'qilmagan notificationlarni o'qildi deb belgilash."""
        now = self._now()
        result = await self.db.execute(
            update(Notification)
            .where(
                Notification.user_id == user_id,
                Notification.is_read == False,
            )
            .values(is_read=True, read_at=now)
        )
        await self.db.commit()
        return result.rowcount

    # ════════════════════════════════════════════════════════════════
    # DELETE
    # ════════════════════════════════════════════════════════════════

    async def delete_notification(
        self,
        notification_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> None:
        result = await self.db.execute(
            select(Notification).where(
                Notification.id == notification_id,
                Notification.user_id == user_id,
            )
        )
        notification = result.scalar_one_or_none()
        if not notification:
            raise ValueError("Notification topilmadi")

        await self.db.delete(notification)
        await self.db.commit()

    async def delete_all_read(self, user_id: uuid.UUID) -> int:
        """O'qilgan barcha notificationlarni o'chirish."""
        result = await self.db.execute(
            select(Notification).where(
                Notification.user_id == user_id,
                Notification.is_read == True,
            )
        )
        notifications = result.scalars().all()
        count = len(notifications)

        for n in notifications:
            await self.db.delete(n)

        await self.db.commit()
        return count

    # ════════════════════════════════════════════════════════════════
    # SETTINGS
    # ════════════════════════════════════════════════════════════════

    async def get_or_create_settings(
        self, user_id: uuid.UUID
    ) -> NotificationSetting:
        result = await self.db.execute(
            select(NotificationSetting).where(
                NotificationSetting.user_id == user_id
            )
        )
        settings = result.scalar_one_or_none()

        if not settings:
            settings = NotificationSetting(user_id=user_id)
            self.db.add(settings)
            await self.db.commit()
            await self.db.refresh(settings)

        return settings

    async def update_settings(
        self,
        user_id: uuid.UUID,
        data: NotificationSettingUpdate,
    ) -> NotificationSetting:
        settings = await self.get_or_create_settings(user_id)

        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(settings, field, value)
        settings.updated_at = self._now()

        await self.db.commit()
        await self.db.refresh(settings)
        return settings
