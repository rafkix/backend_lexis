import re
from datetime import datetime, date
from typing import Optional, List, Generic, TypeVar
from uuid import UUID
from enum import Enum

from pydantic import BaseModel, EmailStr, Field, field_validator

T = TypeVar("T")


# =====================================================
# 🔁 GENERIC
# =====================================================


class ApiResponse(BaseModel, Generic[T]):
    success: bool = True
    data: Optional[T] = None
    message: Optional[str] = None


# =====================================================
# ENUMS
# =====================================================


class UserStatus(str, Enum):
    ACTIVE = "active"
    BLOCKED = "blocked"
    PENDING = "pending"


class CEFRLevel(str, Enum):
    A1 = "A1"
    A2 = "A2"
    B1 = "B1"
    B2 = "B2"
    C1 = "C1"
    C2 = "C2"


class IELTSGoal(str, Enum):
    UNIVERSITY = "university"
    IMMIGRATION = "immigration"
    WORK = "work"
    PERSONAL = "personal"
    OTHER = "other"


class CEFRGoal(str, Enum):
    TRAVEL = "travel"
    BUSINESS = "business"
    ACADEMIC = "academic"
    DAILY = "daily"
    EXAM = "exam"
    OTHER = "other"


# =====================================================
# 📊 META STRUCTURES
# =====================================================


class IELTSMeta(BaseModel):
    current_score: Optional[float] = Field(None, ge=0, le=9)
    listening: Optional[float] = Field(None, ge=0, le=9)
    reading: Optional[float] = Field(None, ge=0, le=9)
    writing: Optional[float] = Field(None, ge=0, le=9)
    speaking: Optional[float] = Field(None, ge=0, le=9)
    target_score: Optional[float] = Field(None, ge=0, le=9)
    target_listening: Optional[float] = Field(None, ge=0, le=9)
    target_reading: Optional[float] = Field(None, ge=0, le=9)
    target_writing: Optional[float] = Field(None, ge=0, le=9)
    target_speaking: Optional[float] = Field(None, ge=0, le=9)
    exam_date: Optional[date] = None
    attempts: Optional[int] = Field(None, ge=0)
    goal: Optional[IELTSGoal] = None
    goal_note: Optional[str] = Field(None, max_length=200)

    @field_validator("current_score", "target_score", mode="before")
    @classmethod
    def round_score(cls, v):
        if v is None:
            return v
        return round(v * 2) / 2


class CEFRMeta(BaseModel):
    level: Optional[CEFRLevel] = None
    target_level: Optional[CEFRLevel] = None
    goal: Optional[CEFRGoal] = None
    goal_note: Optional[str] = Field(None, max_length=200)
    assessed_at: Optional[date] = None


class UserMeta(BaseModel):
    version: int = 1
    bio: Optional[str] = Field(None, max_length=500)
    birth_date: Optional[date] = None
    ielts: Optional[IELTSMeta] = None
    cefr: Optional[CEFRMeta] = None


# =====================================================
# 👤 USER RESPONSE
# =====================================================


class UserResponse(BaseModel):
    id: UUID
    public_id: str
    email: Optional[str] = None
    username: Optional[str] = None
    full_name: Optional[str] = None
    phone: Optional[str] = None
    phone_verified: bool = False
    avatar: Optional[str] = None
    is_verified: bool
    is_active: bool
    status: UserStatus
    roles: List[str] = Field(default_factory=list)
    meta: Optional[UserMeta] = None
    has_password: bool = False
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# =====================================================
# ✏️ UPDATE PROFILE
# =====================================================


class UpdateUserSchema(BaseModel):
    full_name: Optional[str] = Field(None, min_length=1, max_length=255)
    username: Optional[str] = Field(None, min_length=3, max_length=30)
    meta: Optional[UserMeta] = None

    @field_validator("username")
    @classmethod
    def validate_username(cls, v):
        if v is None:
            return v
        if not re.match(r"^[a-zA-Z0-9_]+$", v):
            raise ValueError(
                "Username faqat harf, raqam va _ belgisidan iborat bo'lishi kerak"
            )
        return v.lower()


# =====================================================
# 🖼 AVATAR
# =====================================================


class UpdateAvatarSchema(BaseModel):
    avatar_url: str = Field(..., min_length=10)

    @field_validator("avatar_url")
    @classmethod
    def validate_url(cls, v):
        if not re.match(r"^https?://", v):
            raise ValueError("Avatar URL http:// yoki https:// bilan boshlanishi kerak")
        return v


# =====================================================
# 🔐 PASSWORD
# =====================================================


class ChangePasswordSchema(BaseModel):
    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8)

    @field_validator("new_password")
    @classmethod
    def validate_password(cls, v):
        if " " in v:
            raise ValueError("Parolda bo'shliq bo'lmasligi kerak")
        return v


class SetPasswordSchema(BaseModel):
    new_password: str = Field(..., min_length=8)

    @field_validator("new_password")
    @classmethod
    def validate_password(cls, v):
        if " " in v:
            raise ValueError("Parolda bo'shliq bo'lmasligi kerak")
        return v


# =====================================================
# 📱 DEVICE / SESSION
# =====================================================


class DeviceResponse(BaseModel):
    id: UUID
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    expires_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


# =====================================================
# 🔧 MISC
# =====================================================


class RevokeOthersSchema(BaseModel):
    current_session_id: str = Field(..., min_length=1)


class DeleteAccountSchema(BaseModel):
    password: Optional[str] = None


# =====================================================
# 📞 PHONE UPDATE — 2 bosqichli flow
# =====================================================


class PhoneUpdateRequestSchema(BaseModel):
    """1-bosqich: yangi telefon raqam → SMS OTP yuboriladi."""

    phone: str = Field(..., min_length=7, max_length=20)

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        cleaned = re.sub(r"\s+", "", v)
        if not re.match(r"^\+?[0-9]{7,15}$", cleaned):
            raise ValueError("Noto'g'ri telefon raqam formati")
        return cleaned


class PhoneUpdateVerifySchema(BaseModel):
    """2-bosqich: SMS dagi kodni tasdiqlash."""

    phone: str = Field(..., min_length=7, max_length=20)
    code: str = Field(..., min_length=4, max_length=8)

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        cleaned = re.sub(r"\s+", "", v)
        if not re.match(r"^\+?[0-9]{7,15}$", cleaned):
            raise ValueError("Noto'g'ri telefon raqam formati")
        return cleaned
