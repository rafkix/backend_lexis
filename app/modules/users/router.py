# app/modules/users/router.py
from fastapi import APIRouter, Depends, File, UploadFile, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import User
from app.modules.users.service import UserService
from app.modules.users.schemas import (
    ApiResponse,
    ChangePasswordSchema,
    DeleteAccountSchema,
    DeviceResponse,
    PhoneUpdateRequestSchema,
    PhoneUpdateVerifySchema,
    RevokeOthersSchema,
    SetPasswordSchema,
    UpdateUserSchema,
    UpdateAvatarSchema,
    UserResponse,
)

# ─── Shared response doc blocks ───────────────────────────────────────────────

_400 = {400: {"description": "Bad request — invalid input or business rule violation."}}
_401 = {401: {"description": "Not authenticated — Bearer token missing or invalid."}}
_404 = {404: {"description": "Not found — resource does not exist."}}
_422 = {422: {"description": "Validation error — request body is malformed."}}

_base = {**_401, **_422}


router = APIRouter(
    prefix="/users",
    tags=["Users"],
    dependencies=[Depends(get_current_user)],  # auth required for ALL endpoints
)


def get_user_service(db: AsyncSession = Depends(get_db)) -> UserService:
    return UserService(db)


# ══════════════════════════════════════════════════════════════════════
# PROFILE
# ══════════════════════════════════════════════════════════════════════


@router.get(
    "/me",
    response_model=ApiResponse[UserResponse],
    summary="Get current user profile",
    description="Returns the authenticated user's full profile information.",
    responses={
        200: {"description": "Profile returned successfully."},
        **_401,
    },
)
async def get_me(
    user: User = Depends(get_current_user),
    service: UserService = Depends(get_user_service),
):
    return ApiResponse(data=service._serialize_user(user))


@router.put(
    "/me",
    response_model=ApiResponse[UserResponse],
    summary="Update profile",
    description="Updates the authenticated user's display name, username, or metadata. Only provided fields are changed.",
    responses={
        200: {"description": "Profile updated successfully."},
        **_400,
        **_base,
    },
)
async def update_profile(
    data: UpdateUserSchema,
    user: User = Depends(get_current_user),
    service: UserService = Depends(get_user_service),
):
    result = await service.update_profile(user, data)
    return ApiResponse(data=result["user"], message=result["message"])


@router.delete(
    "/me",
    response_model=ApiResponse[None],
    summary="Delete account",
    description=(
        "Permanently deletes the authenticated user's account. "
        "Password confirmation is required. **This action is irreversible.**"
    ),
    responses={
        200: {"description": "Account deleted successfully."},
        **_400,
        **_base,
    },
)
async def delete_account(
    data: DeleteAccountSchema,
    user: User = Depends(get_current_user),
    service: UserService = Depends(get_user_service),
):
    result = await service.delete_account(user, data.password)
    return ApiResponse(message=result["message"])


# ══════════════════════════════════════════════════════════════════════
# AVATAR
# ══════════════════════════════════════════════════════════════════════


@router.patch(
    "/me/avatar/upload",
    response_model=ApiResponse[dict],
    summary="Upload avatar image",
    description=(
        "Uploads a new avatar for the authenticated user. "
        "Accepted formats: JPEG, PNG, WebP. Maximum file size: **2 MB**."
    ),
    responses={
        200: {"description": "Avatar uploaded and updated successfully."},
        **_400,
        **_base,
    },
)
async def upload_avatar(
    avatar: UploadFile = File(
        ..., description="Image file (JPEG / PNG / WebP, max 2 MB)"
    ),
    user: User = Depends(get_current_user),
    service: UserService = Depends(get_user_service),
):
    result = await service.update_avatar(user, avatar)
    return ApiResponse(data={"avatar": result["avatar"]}, message=result["message"])


@router.patch(
    "/me/avatar/url",
    response_model=ApiResponse[dict],
    summary="Set avatar via CDN URL",
    description="Sets the authenticated user's avatar to an external CDN URL instead of an uploaded file.",
    responses={
        200: {"description": "Avatar URL updated successfully."},
        **_400,
        **_base,
    },
)
async def update_avatar_url(
    data: UpdateAvatarSchema,
    user: User = Depends(get_current_user),
    service: UserService = Depends(get_user_service),
):
    result = await service.confirm_avatar_url(user, data.avatar_url)
    return ApiResponse(data={"avatar": result["avatar"]}, message=result["message"])


# ══════════════════════════════════════════════════════════════════════
# PASSWORD
# ══════════════════════════════════════════════════════════════════════


@router.post(
    "/me/password/set",
    response_model=ApiResponse[None],
    summary="Set password (social users)",
    description=(
        "Allows users who signed up via social login (Google, Apple, etc.) "
        "to set a password for the first time, enabling email/password login."
    ),
    responses={
        200: {"description": "Password set successfully."},
        **_400,
        **_base,
    },
)
async def set_password(
    data: SetPasswordSchema,
    user: User = Depends(get_current_user),
    service: UserService = Depends(get_user_service),
):
    result = await service.set_password(user, data.new_password)
    return ApiResponse(message=result["message"])


@router.post(
    "/me/password/change",
    response_model=ApiResponse[None],
    summary="Change password",
    description="Changes the authenticated user's password. Requires the current password for confirmation.",
    responses={
        200: {"description": "Password changed successfully."},
        **_400,
        **_base,
    },
)
async def change_password(
    data: ChangePasswordSchema,
    user: User = Depends(get_current_user),
    service: UserService = Depends(get_user_service),
):
    result = await service.change_password(
        user=user,
        current_password=data.current_password,
        new_password=data.new_password,
    )
    return ApiResponse(message=result["message"])


# ══════════════════════════════════════════════════════════════════════
# DEVICES / SESSIONS
# ══════════════════════════════════════════════════════════════════════


@router.get(
    "/me/devices",
    response_model=ApiResponse[list[DeviceResponse]],
    summary="List active devices",
    description="Returns all active sessions (devices) for the authenticated user.",
    responses={
        200: {"description": "Active device list returned successfully."},
        **_401,
    },
)
async def get_devices(
    user: User = Depends(get_current_user),
    service: UserService = Depends(get_user_service),
):
    devices = await service.get_devices(user)
    return ApiResponse(data=devices)


@router.delete(
    "/me/devices/{session_id}",
    response_model=ApiResponse[None],
    summary="Revoke a device session",
    description="Logs out a specific device by its session ID. The device will need to re-authenticate.",
    responses={
        200: {"description": "Device session revoked successfully."},
        **_401,
        **_404,
    },
)
async def revoke_device(
    session_id: str,
    user: User = Depends(get_current_user),
    service: UserService = Depends(get_user_service),
):
    result = await service.revoke_device(user, session_id)
    return ApiResponse(message=result["message"])


@router.delete(
    "/me/devices",
    response_model=ApiResponse[None],
    summary="Revoke all other device sessions",
    description=(
        "Logs out all devices except the current one. "
        "Pass the `current_session_id` in the request body to identify which session to keep."
    ),
    responses={
        200: {"description": "All other device sessions revoked successfully."},
        **_400,
        **_base,
    },
)
async def revoke_other_devices(
    data: RevokeOthersSchema,
    user: User = Depends(get_current_user),
    service: UserService = Depends(get_user_service),
):
    result = await service.revoke_other_devices(user, data.current_session_id)
    return ApiResponse(message=result["message"])


# ══════════════════════════════════════════════════════════════════════
# PHONE NUMBER
# ══════════════════════════════════════════════════════════════════════


@router.post(
    "/me/phone/request",
    response_model=ApiResponse[dict],
    summary="Request phone number change (step 1)",
    description=(
        "Sends a 6-digit SMS verification code to the new phone number. "
        "Call `/me/phone/verify` next to confirm the code and apply the change."
    ),
    responses={
        200: {"description": "SMS verification code sent successfully."},
        **_400,
        **_base,
    },
)
async def request_phone_update(
    data: PhoneUpdateRequestSchema,
    user: User = Depends(get_current_user),
    service: UserService = Depends(get_user_service),
):
    result = await service.request_phone_update(user, data.phone)
    return ApiResponse(
        data={"expires_in": result.get("expires_in")},
        message=result["message"],
    )


@router.post(
    "/me/phone/verify",
    response_model=ApiResponse[dict],
    summary="Verify phone number change (step 2)",
    description=(
        "Confirms the SMS code received in step 1 and updates the user's phone number. "
        "The code expires after a short period — request a new one if it has expired."
    ),
    responses={
        200: {"description": "Phone number verified and updated successfully."},
        **_400,
        **_base,
    },
)
async def verify_phone_update(
    data: PhoneUpdateVerifySchema,
    user: User = Depends(get_current_user),
    service: UserService = Depends(get_user_service),
):
    result = await service.verify_phone_update(user, data.phone, data.code)
    return ApiResponse(data={"phone": result.get("phone")}, message=result["message"])
