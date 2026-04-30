# app/modules/auth/router.py
from fastapi import APIRouter, Depends, Request, Response, status

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cookies import set_auth_cookies, clear_auth_cookies
from app.core.database import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import User
from app.modules.auth.service import AuthService
from app.modules.auth.schemas import (
    RegisterRequest,
    LoginRequest,
    TokenResponse,
    RefreshRequest,
    SocialLoginRequest,
    MeResponse,
    LogoutResponse,
    SessionResponse,
    ChangePasswordRequest,
    SetPasswordRequest,
    ForgotPasswordRequest,
    ResetPasswordRequest,
    SendPhoneCodeRequest,
    VerifyPhoneRequest,
    MessageResponse,
)

# ─── Shared response doc blocks ───────────────────────────────────────────────

_400 = {
    400: {
        "description": "Bad request — invalid credentials or business rule violation."
    }
}
_401 = {401: {"description": "Not authenticated — Bearer token missing or expired."}}
_422 = {422: {"description": "Validation error — request body is malformed."}}

_base = {**_400, **_422}
_auth = {**_401, **_422}


router = APIRouter(prefix="/auth", tags=["Auth"])


def get_auth_service(db: AsyncSession = Depends(get_db)) -> AuthService:
    return AuthService(db)


# ══════════════════════════════════════════════════════════════════════
# REGISTER / LOGIN / REFRESH
# ══════════════════════════════════════════════════════════════════════


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user",
    description=(
        "Creates a new user account with email/phone and password. "
        "Returns access and refresh tokens. Auth cookies are also set automatically."
    ),
    responses={
        201: {"description": "User registered successfully. Tokens returned."},
        **_base,
        409: {"description": "Conflict — email, phone, or username is already taken."},
    },
)
async def register(
    payload: RegisterRequest,
    request: Request,
    response: Response,
    service: AuthService = Depends(get_auth_service),
):
    result = await service.register(
        full_name=payload.full_name,
        username=payload.username,
        email=str(payload.email) if payload.email else None,
        phone=payload.phone,
        password=payload.password,
        request=request,
    )
    set_auth_cookies(response, result["access_token"], result["refresh_token"])
    return result


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Login",
    description=(
        "Authenticates a user by email, username, or phone number combined with a password. "
        "Returns access and refresh tokens. Auth cookies are also set automatically."
    ),
    responses={
        200: {"description": "Login successful. Tokens returned."},
        **_base,
        401: {
            "description": "Invalid credentials — identifier or password is incorrect."
        },
    },
)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    service: AuthService = Depends(get_auth_service),
):
    result = await service.login(
        identifier=payload.identifier,
        password=payload.password,
        request=request,
    )
    set_auth_cookies(response, result["access_token"], result["refresh_token"])
    return result


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Refresh access token",
    description=(
        "Issues a new access token using a valid refresh token. "
        "The old refresh token is rotated — a new one is returned and cookies are updated."
    ),
    responses={
        200: {"description": "Tokens refreshed successfully."},
        **_base,
        401: {"description": "Refresh token is invalid or has expired."},
    },
)
async def refresh(
    payload: RefreshRequest,
    request: Request,
    response: Response,
    service: AuthService = Depends(get_auth_service),
):
    result = await service.refresh(payload.refresh_token, request)
    set_auth_cookies(response, result["access_token"], result["refresh_token"])
    return result


# ══════════════════════════════════════════════════════════════════════
# ME
# ══════════════════════════════════════════════════════════════════════


@router.get(
    "/me",
    response_model=MeResponse,
    summary="Get current user",
    description="Returns full profile data for the currently authenticated user.",
    responses={
        200: {"description": "Current user data returned successfully."},
        **_auth,
    },
)
async def me(
    user: User = Depends(get_current_user),
    service: AuthService = Depends(get_auth_service),
):
    return await service.me(user.id)


# ══════════════════════════════════════════════════════════════════════
# SESSIONS
# ══════════════════════════════════════════════════════════════════════


@router.get(
    "/sessions",
    response_model=list[SessionResponse],
    summary="List active sessions",
    description="Returns all active login sessions for the authenticated user across all devices.",
    responses={
        200: {"description": "Active sessions returned successfully."},
        **_auth,
    },
)
async def get_sessions(
    user: User = Depends(get_current_user),
    service: AuthService = Depends(get_auth_service),
):
    return await service.get_sessions(user)


@router.delete(
    "/sessions/{session_id}",
    response_model=MessageResponse,
    summary="Revoke a session",
    description="Logs out a specific session by its ID. The device using that session will need to re-authenticate.",
    responses={
        200: {"description": "Session revoked successfully."},
        **_auth,
        404: {"description": "Session not found."},
    },
)
async def revoke_session(
    session_id: str,
    user: User = Depends(get_current_user),
    service: AuthService = Depends(get_auth_service),
):
    return await service.revoke_session(user, session_id)


# ══════════════════════════════════════════════════════════════════════
# LOGOUT
# ══════════════════════════════════════════════════════════════════════


@router.post(
    "/logout",
    response_model=LogoutResponse,
    summary="Logout",
    description="Invalidates the provided refresh token and clears auth cookies for the current session.",
    responses={
        200: {"description": "Logged out successfully."},
        **_base,
    },
)
async def logout(
    payload: RefreshRequest,
    response: Response,
    service: AuthService = Depends(get_auth_service),
):
    result = await service.logout(payload.refresh_token)
    clear_auth_cookies(response)
    return result


@router.post(
    "/logout-all",
    response_model=LogoutResponse,
    summary="Logout from all devices",
    description="Invalidates all active sessions for the authenticated user and clears auth cookies.",
    responses={
        200: {"description": "Logged out from all devices successfully."},
        **_auth,
    },
)
async def logout_all(
    response: Response,
    user: User = Depends(get_current_user),
    service: AuthService = Depends(get_auth_service),
):
    result = await service.logout_all(user)
    clear_auth_cookies(response)
    return result


# ══════════════════════════════════════════════════════════════════════
# PASSWORD MANAGEMENT
# ══════════════════════════════════════════════════════════════════════


@router.post(
    "/set-password",
    response_model=MessageResponse,
    summary="Set password (social users)",
    description=(
        "Allows users who registered via social login (Google, Telegram) "
        "to set a password for the first time, enabling email/password login."
    ),
    responses={
        200: {"description": "Password set successfully."},
        **_base,
        **_auth,
    },
)
async def set_password(
    payload: SetPasswordRequest,
    user: User = Depends(get_current_user),
    service: AuthService = Depends(get_auth_service),
):
    return await service.set_password(user, payload.new_password)


@router.post(
    "/change-password",
    response_model=MessageResponse,
    summary="Change password",
    description="Changes the authenticated user's password. The current password must be provided for confirmation.",
    responses={
        200: {"description": "Password changed successfully."},
        **_base,
        **_auth,
    },
)
async def change_password(
    payload: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    service: AuthService = Depends(get_auth_service),
):
    return await service.change_password(
        user=user,
        current_password=payload.current_password,
        new_password=payload.new_password,
    )


@router.post(
    "/forgot-password",
    response_model=MessageResponse,
    summary="Request password reset",
    description=(
        "Sends a password reset link to the provided email address. "
        "The link expires after a short period. No error is returned if the email is not registered "
        "(to prevent user enumeration)."
    ),
    responses={
        200: {"description": "Reset email sent if the address is registered."},
        **_base,
    },
)
async def forgot_password(
    payload: ForgotPasswordRequest,
    service: AuthService = Depends(get_auth_service),
):
    return await service.forgot_password(str(payload.email))


@router.post(
    "/reset-password",
    response_model=MessageResponse,
    summary="Reset password via token",
    description="Sets a new password using the token received in the password reset email.",
    responses={
        200: {"description": "Password reset successfully."},
        **_base,
        401: {"description": "Reset token is invalid or has expired."},
    },
)
async def reset_password(
    payload: ResetPasswordRequest,
    service: AuthService = Depends(get_auth_service),
):
    return await service.reset_password(payload.token, payload.new_password)


# ══════════════════════════════════════════════════════════════════════
# PHONE VERIFICATION
# ══════════════════════════════════════════════════════════════════════


@router.post(
    "/phone/send-code",
    response_model=MessageResponse,
    summary="Send SMS verification code",
    description="Sends a 6-digit SMS code to the given phone number for verification.",
    responses={
        200: {"description": "SMS code sent successfully."},
        **_base,
        **_auth,
    },
)
async def send_phone_code(
    payload: SendPhoneCodeRequest,
    user: User = Depends(get_current_user),
    service: AuthService = Depends(get_auth_service),
):
    return await service.send_phone_verification(user, payload.phone)


@router.post(
    "/phone/verify",
    response_model=MessageResponse,
    summary="Verify SMS code",
    description="Confirms the SMS code sent to the phone number and marks it as verified.",
    responses={
        200: {"description": "Phone number verified successfully."},
        **_base,
        **_auth,
    },
)
async def verify_phone(
    payload: VerifyPhoneRequest,
    user: User = Depends(get_current_user),
    service: AuthService = Depends(get_auth_service),
):
    return await service.verify_phone(user, payload.phone, payload.code)


# ══════════════════════════════════════════════════════════════════════
# SOCIAL AUTH
# ══════════════════════════════════════════════════════════════════════


@router.post(
    "/google",
    response_model=TokenResponse,
    summary="Login with Google",
    description=(
        "Authenticates a user via Google OAuth2 ID token. "
        "Creates an account automatically if the email is not registered. "
        "Auth cookies are set on success."
    ),
    responses={
        200: {"description": "Google authentication successful. Tokens returned."},
        **_base,
    },
)
async def google_auth(
    payload: SocialLoginRequest,
    request: Request,
    response: Response,
    service: AuthService = Depends(get_auth_service),
):
    result = await service.google_auth(payload.id_token, request)
    set_auth_cookies(response, result["access_token"], result["refresh_token"])
    return result


@router.post(
    "/telegram",
    response_model=TokenResponse,
    summary="Login with Telegram",
    description=(
        "Authenticates a user via Telegram login widget data. "
        "Creates an account automatically if the Telegram ID is not registered. "
        "Auth cookies are set on success."
    ),
    responses={
        200: {"description": "Telegram authentication successful. Tokens returned."},
        **_base,
    },
)
async def telegram_auth(
    payload: SocialLoginRequest,
    request: Request,
    response: Response,
    service: AuthService = Depends(get_auth_service),
):
    result = await service.telegram_auth(payload.telegram_data, request)
    set_auth_cookies(response, result["access_token"], result["refresh_token"])
    return result
