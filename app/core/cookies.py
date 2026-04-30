from fastapi import Response
from app.core.config import settings


def set_auth_cookies(
    response: Response,
    access_token: str,
    refresh_token: str,
) -> None:
    response.set_cookie(
        key="access_token",
        value=access_token,
        domain=settings.COOKIE_DOMAIN,
        path="/",
        httponly=settings.COOKIE_HTTPONLY,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
        max_age=60 * settings.ACCESS_TOKEN_MINUTES,
    )
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        domain=settings.COOKIE_DOMAIN,
        path="/",
        httponly=settings.COOKIE_HTTPONLY,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
        max_age=60 * 60 * 24 * settings.REFRESH_TOKEN_DAYS,
    )


def clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(key="access_token", domain=settings.COOKIE_DOMAIN, path="/")
    response.delete_cookie(key="refresh_token", domain=settings.COOKIE_DOMAIN, path="/")
