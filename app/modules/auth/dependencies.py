from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from jose import jwt, JWTError
from uuid import UUID

from app.core.config import settings
from app.core.database import get_db
from app.modules.auth.models import User


# =====================================================
# 🔍 TOKEN EXTRACTOR
# =====================================================


def _extract_token(request: Request) -> str:
    """
    Tokenni header yoki cookie dan oladi.
    1. Authorization: Bearer <token>
    2. Cookie: access_token=<token>
    """
    # 1. Header dan tekshirish
    auth = request.headers.get("Authorization")
    if auth:
        parts = auth.split()
        if len(parts) != 2:
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED,
                "Authorization header is in the wrong format",
            )
        scheme, token = parts
        if scheme.lower() != "bearer":
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Carrier scheme required")
        return token

    # 2. Cookie dan tekshirish
    token = request.cookies.get("access_token")
    if token:
        return token

    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required")


# =====================================================
# 👤 CURRENT USER
# =====================================================


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    token = _extract_token(request)

    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.ALGORITHM],
        )
        user_id: str = payload.get("sub")

        if not user_id or not isinstance(user_id, str):
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED, "Token payload is incorrect"
            )

        token_type = payload.get("type")
        if token_type != "access":
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Access token required")

        user_uuid = UUID(user_id)

    except (JWTError, ValueError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token invalid or expired")

    result = await db.execute(
        select(User).options(selectinload(User.roles)).where(User.id == user_uuid)
    )
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found")

    return user


# =====================================================
# 🔓 ACTIVE USER
# =====================================================


async def get_active_user(
    user: User = Depends(get_current_user),
) -> User:
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "User inactive")
    if user.status == "blocked":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "User blocked")
    return user


# =====================================================
# ✅ VERIFIED USER
# =====================================================


async def get_verified_user(
    user: User = Depends(get_active_user),
) -> User:
    if not user.is_verified:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Email not approved")
    return user


def require_roles(*role_names: str):
    for r in role_names:
        if not isinstance(r, str):
            raise ValueError(f"Invalid role: {r}.")

    async def checker(user: User = Depends(get_active_user)) -> User:
        user_roles = {role.name.upper() for role in (user.roles or [])}

        if not user_roles.intersection(r.upper() for r in role_names):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied. Required roles: {', '.join(role_names)}",
            )

        return user

    return checker


# =====================================================
# 🔑 PERMISSION CHECK
# =====================================================


def require_permission(permission: str):
    """
    Foydalanuvchi roliga biriktirilgan permission ni tekshiradi.
    """

    async def checker(user: User = Depends(get_active_user)) -> User:
        permissions = set()
        for role in user.roles:
            for p in getattr(role, "permissions", []):
                permissions.add(p.name)

        if permission not in permissions:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, f"'{permission}' no permission"
            )
        return user

    return checker
