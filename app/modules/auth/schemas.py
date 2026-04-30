from datetime import datetime
from typing import Optional, List
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, model_validator


# =====================================================
# 🔐 TOKEN
# =====================================================


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class RefreshRequest(BaseModel):
    refresh_token: str


# =====================================================
# 🌐 SOCIAL PROVIDER
# =====================================================


class SocialProvider(str, Enum):
    GOOGLE = "google"
    TELEGRAM = "telegram"


# =====================================================
# 🔐 LOGIN
# =====================================================


class LoginRequest(BaseModel):
    identifier: str = Field(..., min_length=3, description="Username / email / telefon")
    password: str = Field(..., min_length=1)


# =====================================================
# 📝 REGISTER
# =====================================================


class RegisterRequest(BaseModel):
    full_name: str = Field(..., min_length=1, max_length=255)
    username: Optional[str] = Field(None, min_length=3, max_length=50)
    email: Optional[EmailStr] = None
    phone: Optional[str] = Field(None, min_length=7, max_length=20)
    password: str = Field(..., min_length=8)

    @model_validator(mode="after")
    def require_contact(self):
        if not self.email and not self.phone:
            raise ValueError("Email yoki telefon raqam talab qilinadi")
        return self


# =====================================================
# 🌐 SOCIAL LOGIN
# =====================================================


class SocialLoginRequest(BaseModel):
    provider: SocialProvider
    id_token: Optional[str] = None
    telegram_data: Optional[dict] = None

    @model_validator(mode="after")
    def check_provider_data(self):
        if self.provider == SocialProvider.GOOGLE and not self.id_token:
            raise ValueError("Google login uchun id_token talab qilinadi")
        if self.provider == SocialProvider.TELEGRAM and not self.telegram_data:
            raise ValueError("Telegram login uchun telegram_data talab qilinadi")
        return self


# =====================================================
# 👤 USER RESPONSE
# =====================================================


class UserResponse(BaseModel):
    id: UUID
    public_id: str
    email: Optional[str] = None
    username: Optional[str] = None
    phone: Optional[str] = None
    full_name: Optional[str] = None
    avatar: Optional[str] = None
    telegram_id: Optional[str] = None
    is_active: bool
    is_verified: bool
    phone_verified: bool
    status: str
    roles: List[str] = []
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# =====================================================
# 👤 ME RESPONSE
# =====================================================


class MeResponse(BaseModel):
    id: UUID
    public_id: str
    full_name: Optional[str] = None
    username: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    phone_verified: bool = False
    telegram_id: Optional[str] = None
    avatar: Optional[str] = None
    is_verified: bool
    is_active: bool
    status: str
    roles: List[str] = []
    meta: Optional[dict] = None
    has_active_subscription: bool = False

    class Config:
        from_attributes = True


# =====================================================
# 🔑 PASSWORD
# =====================================================


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8)

    @model_validator(mode="after")
    def passwords_must_differ(self):
        if self.current_password == self.new_password:
            raise ValueError("Yangi parol eski paroldan farq qilishi kerak")
        return self


class SetPasswordRequest(BaseModel):
    new_password: str = Field(..., min_length=8)


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(..., min_length=8)


# =====================================================
# 📱 SESSION
# =====================================================


class SessionResponse(BaseModel):
    id: UUID
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    is_revoked: bool
    expires_at: datetime
    last_used_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


class RevokeSessionRequest(BaseModel):
    session_id: str


# =====================================================
# 📱 PHONE VERIFICATION
# =====================================================


class SendPhoneCodeRequest(BaseModel):
    phone: str = Field(..., min_length=7, max_length=20)


class VerifyPhoneRequest(BaseModel):
    phone: str = Field(..., min_length=7, max_length=20)
    code: str = Field(..., min_length=4, max_length=8)


# =====================================================
# 🚪 LOGOUT
# =====================================================


class LogoutResponse(BaseModel):
    success: bool
    message: str


# =====================================================
# 🔁 GENERIC RESPONSE
# =====================================================


class MessageResponse(BaseModel):
    success: bool = True
    message: str
