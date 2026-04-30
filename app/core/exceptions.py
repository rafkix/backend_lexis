from fastapi import HTTPException, status


class AuthException(HTTPException):
    def __init__(self, detail: str):
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            headers={"WWW-Authenticate": "Bearer"},
        )


class InvalidCredentialsException(AuthException):
    def __init__(self):
        super().__init__(detail="Login yoki parol noto'g'ri")


class TokenExpiredException(AuthException):
    def __init__(self):
        super().__init__(detail="Token muddati tugagan")


class InvalidTokenException(AuthException):
    def __init__(self):
        super().__init__(detail="Yaroqsiz token")


class PermissionDeniedException(HTTPException):
    def __init__(self, detail: str = "Ruxsat yo'q"):
        super().__init__(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


class NotFoundException(HTTPException):
    def __init__(self, resource: str = "Ma'lumot"):
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{resource} topilmadi",
        )


class AlreadyExistsException(HTTPException):
    def __init__(self, resource: str = "Ma'lumot"):
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{resource} allaqachon mavjud",
        )


class ValidationException(HTTPException):
    def __init__(self, detail: str):
        super().__init__(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=detail,
        )
