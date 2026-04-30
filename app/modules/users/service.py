import hashlib
import logging
import os
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException, UploadFile
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import PhoneVerification, Session, User
from app.core.security import hash_password, verify_password
from app.modules.users.schemas import UserResponse, UserMeta


logger = logging.getLogger(__name__)

UPLOAD_DIR = "static/avatars"
MAX_AVATAR_SIZE = 2 * 1024 * 1024  # 2 MB
ALLOWED_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}

OTP_EXPIRE_MINUTES = 5
OTP_MAX_ATTEMPTS = 5


# =====================================================
# 📤 SMS STUB
# =====================================================


async def _send_sms(phone: str, code: str) -> None:
    """SMS yuborish stub. Real da Twilio/Eskiz/Playmobile ishlatiladi."""
    logger.info("[SMS STUB] %s → kod: %s", phone, code)


def _hash_code(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


# =====================================================
# 👤 USER SERVICE
# =====================================================


class UserService:
    def __init__(self, db: AsyncSession):
        self.db = db

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    # =====================================================
    # 🧠 DEEP MERGE (meta uchun)
    # =====================================================

    def _deep_merge(self, base: dict, incoming: dict) -> dict:
        result = base.copy()
        for k, v in incoming.items():
            if v is None:
                continue
            if k in result and isinstance(result[k], dict) and isinstance(v, dict):
                result[k] = self._deep_merge(result[k], v)
            else:
                result[k] = v
        return result

    # =====================================================
    # 🔄 SERIALIZE USER
    # =====================================================

    def _serialize_user(self, user: User) -> UserResponse:
        meta = None
        if user.meta:
            try:
                meta = UserMeta.model_validate(user.meta)
            except Exception as e:
                logger.warning("UserMeta parse error (user_id=%s): %s", user.id, e)

        return UserResponse(
            id=user.id,
            public_id=user.public_id,
            email=user.email,
            username=user.username,
            full_name=user.full_name,
            phone=user.phone,
            phone_verified=user.phone_verified,
            avatar=user.avatar,
            is_verified=user.is_verified,
            is_active=user.is_active,
            status=user.status.value,
            roles=[r.name for r in user.roles] if user.roles else [],
            meta=meta,
            has_password=bool(user.password_hash),
            created_at=user.created_at,
            updated_at=user.updated_at,
        )

    # =====================================================
    # ✏️ UPDATE PROFILE
    # =====================================================

    async def update_profile(self, user: User, data) -> dict:
        # Username tekshiruvi
        if data.username is not None:
            res = await self.db.execute(
                select(User).where(
                    User.username == data.username,
                    User.id != user.id,
                )
            )
            if res.scalar_one_or_none():
                raise HTTPException(400, "Bu username band")
            user.username = data.username

        # Full name
        if data.full_name is not None:
            user.full_name = data.full_name

        # Meta — deep merge
        if data.meta is not None:
            current_meta: dict = {}
            if user.meta:
                if isinstance(user.meta, dict):
                    current_meta = user.meta
                else:
                    try:
                        current_meta = user.meta.model_dump()
                    except Exception:
                        current_meta = {}

            incoming = data.meta.model_dump(exclude_none=True)
            merged = self._deep_merge(current_meta, incoming)
            merged.setdefault("version", 1)
            user.meta = merged

        await self.db.commit()
        await self.db.refresh(user)
        return {"user": self._serialize_user(user), "message": "Profil yangilandi"}

    # =====================================================
    # 🖼 AVATAR — FILE UPLOAD
    # =====================================================

    async def update_avatar(self, user: User, avatar: UploadFile) -> dict:
        if avatar.content_type not in ALLOWED_MIME_TYPES:
            raise HTTPException(
                400, f"Fayl turi qabul qilinmaydi. Ruxsat etilganlar: jpeg, png, webp"
            )

        content = await avatar.read()
        if len(content) > MAX_AVATAR_SIZE:
            raise HTTPException(400, "Fayl hajmi 2MB dan oshmasligi kerak")

        ext = (avatar.filename or "image").rsplit(".", 1)[-1].lower()
        if ext not in {"jpg", "jpeg", "png", "webp"}:
            ext = "jpg"

        filename = f"{uuid.uuid4()}.{ext}"
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        file_path = os.path.join(UPLOAD_DIR, filename)

        with open(file_path, "wb") as f:
            f.write(content)

        # Eski avatarni o'chirish
        if user.avatar and user.avatar.startswith("/static/avatars/"):
            old_path = user.avatar.lstrip("/")
            if os.path.exists(old_path):
                try:
                    os.remove(old_path)
                except OSError as e:
                    logger.warning("Eski avatar o'chirilmadi: %s", e)

        user.avatar = f"/static/avatars/{filename}"
        await self.db.commit()
        await self.db.refresh(user)

        return {
            "success": True,
            "avatar": user.avatar,
            "message": "Avatar yangilandi",
        }

    # =====================================================
    # 🖼 AVATAR — CDN URL
    # =====================================================

    async def confirm_avatar_url(self, user: User, avatar_url: str) -> dict:
        if not re.match(r"^https?://", avatar_url):
            raise HTTPException(400, "Yaroqsiz avatar URL")

        user.avatar = avatar_url
        await self.db.commit()
        await self.db.refresh(user)
        return {"success": True, "avatar": user.avatar, "message": "Avatar yangilandi"}

    # =====================================================
    # 🔐 CHANGE PASSWORD
    # =====================================================

    async def change_password(
        self, user: User, current_password: str, new_password: str
    ) -> dict:
        if not user.password_hash:
            raise HTTPException(400, "Parol yo'q. set_password dan foydalaning.")

        valid, _ = verify_password(current_password, user.password_hash)
        if not valid:
            raise HTTPException(400, "Joriy parol noto'g'ri")

        user.password_hash = hash_password(new_password)
        await self.db.commit()
        return {"success": True, "message": "Parol o'zgartirildi"}

    # =====================================================
    # 🔑 SET PASSWORD
    # =====================================================

    async def set_password(self, user: User, new_password: str) -> dict:
        if user.password_hash:
            raise HTTPException(
                400, "Parol allaqachon mavjud. change_password dan foydalaning."
            )
        user.password_hash = hash_password(new_password)
        await self.db.commit()
        return {"success": True, "message": "Parol o'rnatildi"}

    # =====================================================
    # 🗑 DELETE ACCOUNT
    # =====================================================

    async def delete_account(self, user: User, password: Optional[str] = None) -> dict:
        if user.password_hash:
            if not password:
                raise HTTPException(
                    400, "Accountni o'chirish uchun parol talab qilinadi"
                )
            valid, _ = verify_password(password, user.password_hash)
            if not valid:
                raise HTTPException(400, "Parol noto'g'ri")

        await self.db.delete(user)
        await self.db.commit()
        return {"success": True, "message": "Account o'chirildi"}

    # =====================================================
    # 📱 DEVICES / SESSIONS
    # =====================================================

    async def get_devices(self, user: User) -> list:
        res = await self.db.execute(
            select(Session)
            .where(
                Session.user_id == user.id,
                Session.is_revoked == False,
                Session.expires_at > self._now(),
            )
            .order_by(Session.created_at.desc())
        )
        return res.scalars().all()

    async def revoke_device(self, user: User, session_id: str) -> dict:
        res = await self.db.execute(
            select(Session).where(
                Session.id == uuid.UUID(session_id),   # ✅
                Session.user_id == user.id,
            )
        )
        session = res.scalar_one_or_none()

        if not session:
            raise HTTPException(404, "Sessiya topilmadi")

        session.is_revoked = True
        await self.db.commit()
        return {"success": True, "message": "Qurilma chiqarildi"}

    async def revoke_other_devices(self, user: User, current_session_id: str) -> dict:
        await self.db.execute(
            update(Session)
            .where(
                Session.user_id == user.id,
                Session.id != current_session_id,
            )
            .values(is_revoked=True)
        )
        await self.db.commit()
        return {"success": True, "message": "Boshqa qurilmalar chiqarildi"}

    # =====================================================
    # 📞 PHONE UPDATE — 1-bosqich: OTP yuborish
    # =====================================================

    async def request_phone_update(self, user: User, phone: str) -> dict:
        # Boshqa foydalanuvchi shu raqamda?
        res = await self.db.execute(
            select(User).where(
                User.phone == phone,
                User.id != user.id,
            )
        )
        if res.scalar_one_or_none():
            raise HTTPException(400, "Bu telefon raqam allaqachon band")

        # Oldingi kodlarni bekor qilish
        await self.db.execute(
            update(PhoneVerification)
            .where(
                PhoneVerification.user_id == user.id,
                PhoneVerification.is_used == False,
            )
            .values(is_used=True)
        )

        # OTP yaratish
        code = str(secrets.randbelow(900000) + 100000)
        expires_at = self._now() + timedelta(minutes=OTP_EXPIRE_MINUTES)

        verification = PhoneVerification(
            user_id=user.id,
            phone=phone,
            code_hash=_hash_code(code),
            expires_at=expires_at,
        )
        self.db.add(verification)
        await self.db.commit()

        await _send_sms(phone, code)

        return {
            "success": True,
            "message": f"SMS yuborildi. Kod {OTP_EXPIRE_MINUTES} daqiqa amal qiladi.",
            "expires_in": OTP_EXPIRE_MINUTES * 60,
        }

    # =====================================================
    # 📞 PHONE UPDATE — 2-bosqich: OTP tasdiqlash
    # =====================================================

    async def verify_phone_update(self, user: User, phone: str, code: str) -> dict:
        res = await self.db.execute(
            select(PhoneVerification)
            .where(
                PhoneVerification.user_id == user.id,
                PhoneVerification.phone == phone,
                PhoneVerification.is_used == False,
            )
            .order_by(PhoneVerification.created_at.desc())
            .limit(1)
        )
        verification = res.scalar_one_or_none()

        if not verification:
            raise HTTPException(400, "Faol verifikatsiya topilmadi. Qaytadan so'rang.")

        if self._now() > verification.expires_at:
            verification.is_used = True
            await self.db.commit()
            raise HTTPException(400, "Kod muddati o'tgan. Qaytadan so'rang.")

        if verification.attempts >= OTP_MAX_ATTEMPTS:
            verification.is_used = True
            await self.db.commit()
            raise HTTPException(
                429,
                f"Ko'p noto'g'ri urinish ({OTP_MAX_ATTEMPTS} ta). Qaytadan so'rang.",
            )

        verification.attempts += 1

        if verification.code_hash != _hash_code(code):
            await self.db.commit()
            remaining = OTP_MAX_ATTEMPTS - verification.attempts
            raise HTTPException(400, f"Noto'g'ri kod. Qolgan urinish: {remaining}")

        verification.is_used = True
        user.phone = phone
        user.phone_verified = True

        await self.db.commit()
        await self.db.refresh(user)

        return {
            "success": True,
            "message": "Telefon raqam tasdiqlandi",
            "phone": user.phone,
        }
