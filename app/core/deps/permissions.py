from fastapi import Depends, HTTPException, status
from app.core.deps.auth import get_current_user
from app.modules.auth.models import User


def require_permission(permission: str):
    async def checker(user: User = Depends(get_current_user)):

        # 🔥 superadmin bypass
        if any(role.name == "superadmin" for role in user.roles):
            return user

        user_permissions = {
            perm.name
            for role in user.roles
            for perm in role.permissions
        }

        if permission not in user_permissions:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Permission denied",
            )

        return user

    return checker