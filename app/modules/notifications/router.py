# app/modules/notifications/router.py
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query, HTTPException, status

from app.modules.auth.dependencies import get_current_user, require_roles
from app.modules.auth.models import User
from app.modules.notifications.dependencies import get_notification_service
from app.modules.notifications.service import NotificationService
from app.modules.notifications.schemas import (
    NotificationOut,
    NotificationCreate,
    PaginatedNotifications,
    UnreadCount,
    NotificationSettingOut,
    NotificationSettingUpdate,
    AdminNotificationStats,
    BroadcastResponse,
    DeleteCountResponse,
    MarkAllResponse,
)
from app.modules.notifications.models import NotificationType

# ─── Shared error response docs ───────────────────────────────────────────────

_401 = {401: {"description": "Not authenticated — Bearer token missing or invalid."}}
_403 = {
    403: {
        "description": "Forbidden — you do not have permission to access this resource."
    }
}
_404 = {
    404: {
        "description": "Not found — the requested notification does not exist or belongs to another user."
    }
}
_401_403 = {**_401, **_403}

_admin_deps = [Depends(require_roles("ADMIN"))]

# ══════════════════════════════════════════════════════════════════════
# Single router  →  /notifications/...
# ══════════════════════════════════════════════════════════════════════

router = APIRouter(
    prefix="/notifications",
    tags=["Notifications"],
    dependencies=[Depends(get_current_user)],
)


# ─────────────────────────────────────────────────────────────────────
# User endpoints
# ─────────────────────────────────────────────────────────────────────


@router.get(
    "",
    response_model=PaginatedNotifications,
    summary="List notifications",
    description=(
        "Returns a paginated list of the authenticated user's notifications. "
        "Optionally filter by read status or notification type."
    ),
    responses={
        200: {"description": "Paginated notification list returned successfully."},
        **_401,
    },
)
async def list_notifications(
    page: int = Query(1, ge=1, description="Page number (starts at 1)"),
    size: int = Query(
        20, ge=1, le=100, description="Number of items per page (max 100)"
    ),
    unread_only: bool = Query(
        False, description="When true, returns only unread notifications"
    ),
    type: Optional[NotificationType] = Query(
        None, description="Filter by notification type"
    ),
    user: User = Depends(get_current_user),
    service: NotificationService = Depends(get_notification_service),
):
    return await service.get_notifications(user.id, page, size, unread_only, type)


@router.get(
    "/unread-count",
    response_model=UnreadCount,
    summary="Get unread notification count",
    description="Returns the total number of unread notifications for the authenticated user.",
    responses={
        200: {"description": "Unread count returned successfully."},
        **_401,
    },
)
async def unread_count(
    user: User = Depends(get_current_user),
    service: NotificationService = Depends(get_notification_service),
):
    count = await service.get_unread_count(user.id)
    return {"count": count}


@router.get(
    "/settings",
    response_model=NotificationSettingOut,
    summary="Get notification settings",
    description=(
        "Returns the notification preferences for the authenticated user. "
        "If no settings exist yet, default settings are created and returned."
    ),
    responses={
        200: {
            "description": "Settings returned (or created with defaults) successfully."
        },
        **_401,
    },
)
async def get_settings(
    user: User = Depends(get_current_user),
    service: NotificationService = Depends(get_notification_service),
):
    return await service.get_or_create_settings(user.id)


@router.patch(
    "/settings",
    response_model=NotificationSettingOut,
    summary="Update notification settings",
    description=(
        "Updates the authenticated user's notification preferences "
        "(e.g. push, email, SMS toggles). Only provided fields are updated."
    ),
    responses={
        200: {"description": "Settings updated successfully."},
        **_401,
        422: {"description": "Validation error — invalid field values provided."},
    },
)
async def update_settings(
    data: NotificationSettingUpdate,
    user: User = Depends(get_current_user),
    service: NotificationService = Depends(get_notification_service),
):
    return await service.update_settings(user.id, data)


@router.patch(
    "/{notification_id}/read",
    response_model=NotificationOut,
    summary="Mark notification as read",
    description="Marks a single notification as read. The notification must belong to the authenticated user.",
    responses={
        200: {"description": "Notification marked as read successfully."},
        **_401,
        **_404,
    },
)
async def mark_as_read(
    notification_id: uuid.UUID,
    user: User = Depends(get_current_user),
    service: NotificationService = Depends(get_notification_service),
):
    try:
        return await service.mark_as_read(notification_id, user.id)
    except ValueError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post(
    "/read-all",
    response_model=MarkAllResponse,
    summary="Mark all notifications as read",
    description="Marks every unread notification for the authenticated user as read in a single operation.",
    responses={
        200: {"description": "All notifications marked as read successfully."},
        **_401,
    },
)
async def mark_all_as_read(
    user: User = Depends(get_current_user),
    service: NotificationService = Depends(get_notification_service),
):
    count = await service.mark_all_as_read(user.id)
    return {"marked": count, "message": f"{count} notification(s) marked as read."}


@router.delete(
    "/read",
    response_model=DeleteCountResponse,
    summary="Delete all read notifications",
    description="Permanently deletes all notifications that have already been read by the authenticated user.",
    responses={
        200: {"description": "Read notifications deleted successfully."},
        **_401,
    },
)
async def delete_all_read(
    user: User = Depends(get_current_user),
    service: NotificationService = Depends(get_notification_service),
):
    count = await service.delete_all_read(user.id)
    return {"deleted": count, "message": f"{count} read notification(s) deleted."}


@router.delete(
    "/{notification_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a notification",
    description="Permanently deletes a single notification. The notification must belong to the authenticated user.",
    responses={
        204: {"description": "Notification deleted successfully. No content returned."},
        **_401,
        **_404,
    },
)
async def delete_notification(
    notification_id: uuid.UUID,
    user: User = Depends(get_current_user),
    service: NotificationService = Depends(get_notification_service),
):
    try:
        await service.delete_notification(notification_id, user.id)
    except ValueError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(e))


# ─────────────────────────────────────────────────────────────────────
# Admin endpoints  →  /notifications/admin/...
# ─────────────────────────────────────────────────────────────────────


@router.post(
    "/admin/broadcast",
    response_model=BroadcastResponse,
    status_code=status.HTTP_201_CREATED,
    summary="[Admin] Broadcast notification",
    description=(
        "Sends a notification to all users or to a specific list of user IDs. "
        "Leave `user_ids` empty to broadcast to every user in the system. "
        "**Requires admin role.**"
    ),
    dependencies=_admin_deps,
    responses={
        201: {"description": "Notification broadcast successfully."},
        **_401_403,
        422: {"description": "Validation error — invalid request body or user IDs."},
    },
)
async def broadcast_notification(
    data: NotificationCreate,
    user_ids: Optional[list[uuid.UUID]] = Query(
        None,
        description="Target user IDs. Omit to send to all users.",
    ),
    service: NotificationService = Depends(get_notification_service),
):
    count = await service.broadcast(data, user_ids)
    return {"sent": count, "message": f"Notification sent to {count} user(s)."}


@router.get(
    "/admin/stats",
    response_model=AdminNotificationStats,
    summary="[Admin] Notification statistics",
    description=(
        "Returns system-wide notification statistics including total count, "
        "unread count, per-type breakdown, and activity in the last 24 hours. "
        "**Requires admin role.**"
    ),
    dependencies=_admin_deps,
    responses={
        200: {"description": "Statistics returned successfully."},
        **_401_403,
    },
)
async def notification_stats(
    service: NotificationService = Depends(get_notification_service),
):
    return await service.get_stats()


@router.get(
    "/admin/user/{user_id}",
    response_model=PaginatedNotifications,
    summary="[Admin] List a user's notifications",
    description=(
        "Returns paginated notifications for any user by their ID. "
        "Supports the same filters as the user-facing list endpoint. "
        "**Requires admin role.**"
    ),
    dependencies=_admin_deps,
    responses={
        200: {"description": "User notifications returned successfully."},
        **_401_403,
        404: {"description": "User not found."},
    },
)
async def admin_list_user_notifications(
    user_id: uuid.UUID,
    page: int = Query(1, ge=1, description="Page number"),
    size: int = Query(20, ge=1, le=100, description="Items per page"),
    unread_only: bool = Query(False, description="Only unread notifications"),
    type: Optional[NotificationType] = Query(None, description="Filter by type"),
    service: NotificationService = Depends(get_notification_service),
):
    return await service.get_notifications(user_id, page, size, unread_only, type)


@router.delete(
    "/admin/user/{user_id}",
    response_model=DeleteCountResponse,
    summary="[Admin] Clear all notifications for a user",
    description=(
        "Permanently deletes **all** notifications for the given user, "
        "regardless of read status. This action is irreversible. "
        "**Requires admin role.**"
    ),
    dependencies=_admin_deps,
    responses={
        200: {"description": "All user notifications deleted successfully."},
        **_401_403,
        404: {"description": "User not found."},
    },
)
async def clear_user_notifications(
    user_id: uuid.UUID,
    service: NotificationService = Depends(get_notification_service),
):
    count = await service.delete_all_for_user(user_id)
    return {
        "deleted": count,
        "message": f"{count} notification(s) deleted for user {user_id}.",
    }


@router.patch(
    "/admin/{notification_id}",
    response_model=NotificationOut,
    summary="[Admin] Update a notification",
    description=(
        "Edits the content or type of any notification by ID. "
        "Useful for correcting broadcast messages. "
        "**Requires admin role.**"
    ),
    dependencies=_admin_deps,
    responses={
        200: {"description": "Notification updated successfully."},
        **_401_403,
        **_404,
        422: {"description": "Validation error — invalid field values."},
    },
)
async def admin_update_notification(
    notification_id: uuid.UUID,
    data: NotificationCreate,
    service: NotificationService = Depends(get_notification_service),
):
    try:
        return await service.admin_update(notification_id, data)
    except ValueError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(e))
