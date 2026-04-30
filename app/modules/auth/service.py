import hmac
import hashlib
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
from fastapi import HTTPException, Request
from sqlalchemy import select, or_, update, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

from app.core.config import settings
from app.core.email import get_reset_email_html, send_email
from app.core.security import create_access_token, hash_password, verify_password
from app.core.exceptions import (
    InvalidCredentialsException,
    AlreadyExistsException,
    NotFoundException,
)
from app.modules.auth.models import (
    User,
    Session,
    Role,
    SocialAccount,
    AuthProvider,
    AuthLog,
    AuthAction,
    UserStatus,
    PhoneVerification,
    PasswordResetToken,
)

logger = logging.getLogger(__name__)


def generate_sms_code() -> str:
    """6 xonali tasodifiy SMS kodi."""
    return str(secrets.randbelow(900000) + 100000)


class AuthService:
    OTP_TTL_SECONDS = 300  # 5 daqiqa
    RESEND_COOLDOWN = 60  # 1 daqiqa
    MAX_ATTEMPTS = 5

    def __init__(self, db: AsyncSession):
        self.db = db

    # =====================================================
    # 🧠 PRIVATE HELPERS
    # =====================================================

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    def _hash(self, value: str) -> str:
        return bcrypt.hashpw(value.encode(), bcrypt.gensalt()).decode()

    def _verify_hash(self, value: str, hashed: str) -> bool:
        try:
            return bcrypt.checkpw(value.encode(), hashed.encode())
        except Exception:
            return False

    def _normalize_phone(self, phone: str) -> str:
        return phone.replace(" ", "").replace("+", "").replace("-", "")

    def _make_refresh_token(self) -> tuple[str, str]:
        """(refresh_token, jti) qaytaradi. Format: jti.random"""
        jti = secrets.token_urlsafe(32)
        token = f"{jti}.{secrets.token_urlsafe(64)}"
        return token, jti

    # =====================================================
    # 🏷️ UNIQUE USERNAME
    # =====================================================

    async def _generate_unique_username(self, base: Optional[str] = None) -> str:
        while True:
            if base:
                username = f"{base}_{secrets.randbelow(10000)}"
            else:
                username = f"user{secrets.randbelow(10**8)}"

            result = await self.db.execute(
                select(User.id).where(User.username == username)
            )
            if not result.scalar_one_or_none():
                return username

    # =====================================================
    # 📝 AUTH LOG
    # =====================================================

    async def _log(
        self,
        user_id: Optional[str],
        action: AuthAction,
        request: Optional[Request] = None,
        status: str = "success",
        error: Optional[str] = None,
    ):
        try:
            async with self.db.begin_nested():
                log_entry = AuthLog(
                    user_id=uuid.UUID(user_id) if user_id else None,
                    action=action,
                    status=status,
                    error_message=error,
                    ip_address=(
                        request.client.host if request and request.client else None
                    ),
                    user_agent=(request.headers.get("user-agent") if request else None),
                )
                self.db.add(log_entry)
        except Exception as e:
            logger.warning("Auth log yozib bo'lmadi: %s", e)

    # =====================================================
    # 👑 DEFAULT ROLE
    # =====================================================

    async def _attach_default_role(self, user: User) -> None:
        result = await self.db.execute(select(Role).where(Role.name == "USER"))
        role = result.scalar_one_or_none()

        if not role:
            role = Role(name="USER", description="Default foydalanuvchi roli")
            self.db.add(role)
            await self.db.flush()

        # async context da lazy load bo'lmaydi — refresh kerak
        await self.db.refresh(user, attribute_names=["roles"])

        if role not in user.roles:
            user.roles.append(role)

    # =====================================================
    # 🔐 CREATE SESSION
    # =====================================================

    async def _create_session(self, user: User, request: Request) -> dict:
        access = create_access_token({"sub": str(user.id)})
        refresh, jti = self._make_refresh_token()

        session = Session(
            user_id=user.id,
            refresh_token_jti=jti,
            refresh_token_hash=self._hash(refresh),
            expires_at=self._now() + timedelta(days=settings.REFRESH_TOKEN_DAYS),
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
        self.db.add(session)
        user.last_login_at = self._now()

        await self._log(str(user.id), AuthAction.LOGIN, request)
        await self.db.commit()

        return {
            "access_token": access,
            "refresh_token": refresh,
            "token_type": "bearer",
            "expires_in": settings.ACCESS_TOKEN_MINUTES * 60,
        }

    # =====================================================
    # 📝 REGISTER
    # =====================================================

    async def register(
        self,
        full_name: str,
        username: Optional[str],
        email: Optional[str],
        phone: Optional[str],
        password: str,
        request: Request,
    ) -> dict:
        # Mavjud foydalanuvchi tekshiruvi
        conditions = []
        if username:
            conditions.append(User.username == username.lower())
        if email:
            conditions.append(User.email == email.lower())
        if phone:
            conditions.append(User.phone == self._normalize_phone(phone))

        if conditions:
            result = await self.db.execute(select(User).where(or_(*conditions)))
            if result.scalar_one_or_none():
                raise AlreadyExistsException("Foydalanuvchi")

        user = User(
            full_name=full_name,
            username=username.lower() if username else None,
            email=email.lower() if email else None,
            phone=self._normalize_phone(phone) if phone else None,
            password_hash=hash_password(password),
            status=UserStatus.ACTIVE,
            is_active=True,
        )
        self.db.add(user)
        await self.db.flush()

        await self._attach_default_role(user)
        await self._log(str(user.id), AuthAction.REGISTER, request)
        await self.db.commit()

        return await self._create_session(user, request)

    # =====================================================
    # 🔐 LOGIN
    # =====================================================

    async def login(
        self,
        identifier: str,
        password: str,
        request: Request,
    ) -> dict:
        normalized = self._normalize_phone(identifier)

        result = await self.db.execute(
            select(User)
            .options(selectinload(User.roles))
            .where(
                or_(
                    User.username == identifier.lower(),
                    User.email == identifier.lower(),
                    User.phone == normalized,
                )
            )
        )
        user = result.unique().scalar_one_or_none()

        if not user or not user.password_hash:
            await self._log(
                None, AuthAction.LOGIN, request, "failed", "Noto'g'ri login"
            )
            raise InvalidCredentialsException()

        is_valid, needs_rehash = verify_password(password, user.password_hash)
        if not is_valid:
            await self._log(
                str(user.id), AuthAction.LOGIN, request, "failed", "Noto'g'ri parol"
            )
            raise InvalidCredentialsException()

        if needs_rehash:
            user.password_hash = hash_password(password)

        if user.status == UserStatus.BLOCKED:
            await self._log(
                str(user.id), AuthAction.LOGIN, request, "failed", "Bloklangan"
            )
            raise HTTPException(403, "Foydalanuvchi bloklangan")

        if not user.is_active:
            await self._log(
                str(user.id), AuthAction.LOGIN, request, "failed", "Faol emas"
            )
            raise HTTPException(403, "Foydalanuvchi faol emas")

        return await self._create_session(user, request)

    # =====================================================
    # 🔄 REFRESH TOKEN
    # =====================================================

    async def refresh(
        self,
        refresh_token: str,
        request: Optional[Request] = None,
    ) -> dict:
        try:
            jti, _ = refresh_token.split(".", 1)
        except ValueError:
            raise HTTPException(401, "Token formati noto'g'ri")

        result = await self.db.execute(
            select(Session).where(
                Session.refresh_token_jti == jti,
                Session.is_revoked == False,
                Session.expires_at > self._now(),
            )
        )
        session = result.scalar_one_or_none()

        if not session or not self._verify_hash(
            refresh_token, session.refresh_token_hash
        ):
            raise HTTPException(401, "Refresh token yaroqsiz")

        # Eski sessiyani o'chirish (token rotation)
        session.is_revoked = True

        new_refresh, new_jti = self._make_refresh_token()
        new_session = Session(
            user_id=session.user_id,
            refresh_token_jti=new_jti,
            refresh_token_hash=self._hash(new_refresh),
            expires_at=self._now() + timedelta(days=settings.REFRESH_TOKEN_DAYS),
            ip_address=request.client.host if request and request.client else None,
            user_agent=request.headers.get("user-agent") if request else None,
        )
        self.db.add(new_session)

        access = create_access_token({"sub": str(session.user_id)})
        await self._log(str(session.user_id), AuthAction.REFRESH, request)
        await self.db.commit()

        return {
            "access_token": access,
            "refresh_token": new_refresh,
            "token_type": "bearer",
            "expires_in": settings.ACCESS_TOKEN_MINUTES * 60,
        }

    # =====================================================
    # 🚪 LOGOUT
    # =====================================================

    async def logout(self, refresh_token: str) -> dict:
        try:
            jti, _ = refresh_token.split(".", 1)
        except ValueError:
            raise HTTPException(401, "Token formati noto'g'ri")

        result = await self.db.execute(
            select(Session).where(
                Session.refresh_token_jti == jti,
                Session.is_revoked == False,
            )
        )
        session = result.scalar_one_or_none()

        if session and self._verify_hash(refresh_token, session.refresh_token_hash):
            session.is_revoked = True
            await self._log(str(session.user_id), AuthAction.LOGOUT)
            await self.db.commit()

        return {"success": True, "message": "Tizimdan chiqildi"}

    async def logout_all(self, user: User) -> dict:
        await self.db.execute(
            update(Session).where(Session.user_id == user.id).values(is_revoked=True)
        )
        await self.db.commit()
        return {"success": True, "message": "Barcha sessiyalar bekor qilindi"}

    # =====================================================
    # 👤 ME
    # =====================================================

    async def me(self, user_id: uuid.UUID) -> dict:  # ✅ str → uuid.UUID
        result = await self.db.execute(
            select(User)
            .options(selectinload(User.roles))
            .where(User.id == user_id)  # ✅ UUID object, string emas
        )
        user = result.unique().scalar_one_or_none()

        if not user:
            raise NotFoundException("Foydalanuvchi")

        # Aktiv obuna bormi tekshirish
        try:
            from app.modules.billing.models import Subscription

            sub_result = await self.db.execute(
                select(Subscription).where(
                    Subscription.user_id == user.id,
                    Subscription.is_active == True,
                    Subscription.end_date > self._now(),
                )
            )
            has_active_subscription = sub_result.scalar_one_or_none() is not None
        except Exception:
            has_active_subscription = False

        return {
            "id": user.id,
            "public_id": user.public_id,
            "full_name": user.full_name,
            "username": user.username,
            "email": user.email,
            "phone": user.phone,
            "phone_verified": user.phone_verified,
            "telegram_id": user.telegram_id,
            "avatar": user.avatar,
            "is_verified": user.is_verified,
            "is_active": user.is_active,
            "status": user.status.value,
            "roles": [r.name for r in user.roles],
            "meta": user.meta,
            "has_active_subscription": has_active_subscription,
        }

    # =====================================================
    # 📱 SESSION MANAGEMENT
    # =====================================================

    async def get_sessions(self, user: User) -> list:
        result = await self.db.execute(
            select(Session)
            .where(Session.user_id == user.id)
            .order_by(Session.created_at.desc())
        )
        return result.scalars().all()

    async def revoke_session(self, user: User, session_id: str) -> dict:
        result = await self.db.execute(
            select(Session).where(
                Session.id == uuid.UUID(session_id),  # ✅
                Session.user_id == user.id,  # ✅ user.id allaqachon UUID
            )
        )
        session = result.scalar_one_or_none()

        if not session:
            raise NotFoundException("Sessiya")

        session.is_revoked = True
        await self.db.commit()
        return {"success": True, "message": "Sessiya bekor qilindi"}

    # =====================================================
    # 🔑 PASSWORD MANAGEMENT
    # =====================================================

    async def set_password(self, user: User, new_password: str) -> dict:
        if user.password_hash:
            raise HTTPException(
                400, "Parol allaqachon mavjud. change_password dan foydalaning."
            )
        user.password_hash = hash_password(new_password)
        await self.db.commit()
        return {"success": True, "message": "Parol o'rnatildi"}

    async def change_password(
        self,
        user: User,
        current_password: str,
        new_password: str,
    ) -> dict:
        if not user.password_hash:
            raise HTTPException(400, "Parol yo'q. set_password dan foydalaning.")

        is_valid, _ = verify_password(current_password, user.password_hash)
        if not is_valid:
            raise HTTPException(400, "Joriy parol noto'g'ri")

        user.password_hash = hash_password(new_password)
        await self._log(str(user.id), AuthAction.PASSWORD_CHANGE)
        await self.db.commit()
        return {"success": True, "message": "Parol o'zgartirildi"}

    async def forgot_password(self, email: str) -> dict:
        result = await self.db.execute(select(User).where(User.email == email.lower()))
        user = result.scalar_one_or_none()

        generic = {
            "success": True,
            "message": "Agar email mavjud bo'lsa, tiklash havolasi yuborildi",
        }

        if not user:
            return generic

        # Eski tokenlarni o'chirish
        await self.db.execute(
            delete(PasswordResetToken).where(PasswordResetToken.user_id == user.id)
        )

        token = PasswordResetToken(
            user_id=user.id,
            token=PasswordResetToken.generate_token(),
            expires_at=self._now() + timedelta(hours=1),
        )
        self.db.add(token)
        await self.db.commit()

        reset_link = f"https://lexis.uz/reset-password?token={token.token}"
        logger.info("Parol tiklash havolasi [%s]: %s", email, reset_link)

        # TODO: Email yuborish (FastMail)
        html = get_reset_email_html(reset_link)

        await send_email(
            to=user.email,
            subject="Reset your password",
            body=html
        )
        return generic

    async def reset_password(self, token: str, new_password: str) -> dict:
        result = await self.db.execute(
            select(PasswordResetToken).where(
                PasswordResetToken.token == token,
                PasswordResetToken.is_used == False,
            )
        )
        reset_token = result.scalar_one_or_none()

        if not reset_token or reset_token.is_expired:
            raise HTTPException(400, "Token yaroqsiz yoki muddati tugagan")

        user_result = await self.db.execute(
            select(User).where(User.id == reset_token.user_id)
        )
        user = user_result.scalar_one_or_none()

        if not user:
            raise NotFoundException("Foydalanuvchi")

        user.password_hash = hash_password(new_password)
        reset_token.is_used = True

        # Xavfsizlik uchun barcha sessiyalarni o'chirish
        await self.db.execute(
            update(Session).where(Session.user_id == user.id).values(is_revoked=True)
        )

        await self.db.commit()
        return {"success": True, "message": "Parol muvaffaqiyatli tiklandi"}

    # =====================================================
    # 📱 PHONE VERIFICATION
    # =====================================================

    async def send_phone_verification(self, user: User, phone: str) -> dict:
        phone = self._normalize_phone(phone)

        # Cooldown tekshiruvi
        result = await self.db.execute(
            select(PhoneVerification)
            .where(PhoneVerification.user_id == user.id)
            .order_by(PhoneVerification.created_at.desc())
            .limit(1)
        )
        last = result.scalar_one_or_none()

        if last:
            diff = (self._now() - last.created_at).total_seconds()
            if diff < self.RESEND_COOLDOWN:
                wait = int(self.RESEND_COOLDOWN - diff)
                raise HTTPException(
                    429, f"Yangi kod so'rashdan oldin {wait} soniya kuting"
                )

        # Eski kodlarni bekor qilish
        await self.db.execute(
            update(PhoneVerification)
            .where(
                PhoneVerification.user_id == user.id,
                PhoneVerification.phone == phone,
                PhoneVerification.is_used == False,
            )
            .values(is_used=True)
        )

        code = generate_sms_code()
        verification = PhoneVerification(
            user_id=user.id,
            phone=phone,
            code_hash=self._hash(code),
            expires_at=self._now() + timedelta(seconds=self.OTP_TTL_SECONDS),
        )
        self.db.add(verification)
        await self.db.commit()

        # TODO: SMS yuborish (SMS Gateway)
        logger.info("[SMS] %s → kod: %s", phone, code)

        return {
            "success": True,
            "message": f"Kod yuborildi. {self.OTP_TTL_SECONDS // 60} daqiqa amal qiladi.",
        }

    async def verify_phone(self, user: User, phone: str, code: str) -> dict:
        phone = self._normalize_phone(phone)

        result = await self.db.execute(
            select(PhoneVerification)
            .where(
                PhoneVerification.user_id == user.id,
                PhoneVerification.phone == phone,
                PhoneVerification.is_used == False,
            )
            .order_by(PhoneVerification.created_at.desc())
            .limit(1)
        )
        verification = result.scalar_one_or_none()

        if not verification:
            raise HTTPException(400, "Verifikatsiya topilmadi. Qaytadan so'rang.")

        if verification.expires_at < self._now():
            verification.is_used = True
            await self.db.commit()
            raise HTTPException(410, "Kod muddati tugagan. Qaytadan so'rang.")

        if verification.attempts >= self.MAX_ATTEMPTS:
            verification.is_used = True
            await self.db.commit()
            raise HTTPException(429, "Ko'p noto'g'ri urinish. Qaytadan so'rang.")

        if not self._verify_hash(code, verification.code_hash):
            verification.attempts += 1
            await self.db.commit()
            remaining = self.MAX_ATTEMPTS - verification.attempts
            raise HTTPException(400, f"Noto'g'ri kod. {remaining} urinish qoldi.")

        verification.is_used = True
        user.phone = phone
        user.phone_verified = True
        await self.db.commit()

        return {"success": True, "message": "Telefon raqam tasdiqlandi"}

    # =====================================================
    # 🌐 GOOGLE AUTH
    # =====================================================

    def _verify_google_token(self, token: str) -> dict:
        try:
            return id_token.verify_oauth2_token(
                token,
                google_requests.Request(),
                settings.GOOGLE_CLIENT_ID,
            )
        except Exception as e:
            logger.warning("Google token xato: %s", e)
            raise HTTPException(401, "Google token yaroqsiz")

    async def google_auth(self, id_token_str: str, request: Request) -> dict:
        google_data = self._verify_google_token(id_token_str)
        provider_id = google_data["sub"]
        email = google_data.get("email", "").lower()

        # Mavjud Google account tekshiruvi
        result = await self.db.execute(
            select(SocialAccount)
            .options(selectinload(SocialAccount.user).selectinload(User.roles))
            .where(
                SocialAccount.provider == AuthProvider.GOOGLE,
                SocialAccount.provider_id == provider_id,
            )
        )
        account = result.scalar_one_or_none()
        if account:
            return await self._create_session(account.user, request)

        # Email bo'yicha mavjud user tekshiruvi
        user = None
        if email:
            user_result = await self.db.execute(
                select(User)
                .options(selectinload(User.roles))
                .where(User.email == email)
            )
            user = user_result.scalar_one_or_none()

        # Yangi foydalanuvchi yaratish
        if not user:
            user = User(
                username=await self._generate_unique_username(),
                email=email or None,
                full_name=google_data.get("name"),
                avatar=google_data.get("picture"),
                is_verified=True,
                status=UserStatus.ACTIVE,
                is_active=True,
            )
            self.db.add(user)
            await self.db.flush()
            await self._attach_default_role(user)

        # Google account ni bog'lash
        social_account = SocialAccount(
            user_id=user.id,
            provider=AuthProvider.GOOGLE,
            provider_id=provider_id,
            email=email or None,
            email_verified=google_data.get("email_verified", False),
        )
        self.db.add(social_account)
        await self.db.commit()

        return await self._create_session(user, request)

    # =====================================================
    # 🤖 TELEGRAM AUTH
    # =====================================================

    def _verify_telegram_data(self, data: dict) -> dict:
        data = data.copy()
        check_hash = data.pop("hash", None)

        if not check_hash:
            raise HTTPException(401, "Telegram hash yo'q")

        data_check = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
        secret = hashlib.sha256(settings.TELEGRAM_BOT_TOKEN.encode()).digest()
        calculated = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()

        if not hmac.compare_digest(calculated, check_hash):
            raise HTTPException(401, "Telegram imzosi yaroqsiz")

        return data

    async def telegram_auth(self, payload: dict, request: Request) -> dict:
        telegram_data = self._verify_telegram_data(payload)
        telegram_id = str(telegram_data["id"])

        # Mavjud Telegram account tekshiruvi
        result = await self.db.execute(
            select(SocialAccount)
            .options(selectinload(SocialAccount.user).selectinload(User.roles))
            .where(
                SocialAccount.provider == AuthProvider.TELEGRAM,
                SocialAccount.provider_id == telegram_id,
            )
        )
        account = result.scalar_one_or_none()
        if account:
            return await self._create_session(account.user, request)

        # Yangi foydalanuvchi yaratish
        first = telegram_data.get("first_name", "")
        last = telegram_data.get("last_name", "")
        full_name = f"{first} {last}".strip() or None

        user = User(
            username=await self._generate_unique_username(
                telegram_data.get("username")
            ),
            full_name=full_name,
            telegram_id=telegram_id,
            is_verified=True,
            status=UserStatus.ACTIVE,
            is_active=True,
        )
        self.db.add(user)
        await self.db.flush()
        await self._attach_default_role(user)

        # Telegram account ni bog'lash
        social_account = SocialAccount(
            user_id=user.id,
            provider=AuthProvider.TELEGRAM,
            provider_id=telegram_id,
        )
        self.db.add(social_account)
        await self.db.commit()

        return await self._create_session(user, request)
