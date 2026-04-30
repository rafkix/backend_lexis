from typing import List
from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
import json


class Settings(BaseSettings):

    # =========================
    # ENV
    # =========================
    ENV: str = "local"
    DEBUG: bool = False
    PROJECT_NAME: str = "Lexis Auth Backend"

    # =========================
    # DATABASE
    # =========================
    DATABASE_URL: str

    # =========================
    # JWT
    # =========================
    JWT_SECRET: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_MINUTES: int = 15
    REFRESH_TOKEN_DAYS: int = 7

    # =========================
    # GOOGLE
    # =========================
    GOOGLE_CLIENT_ID: str

    # =========================
    # TELEGRAM
    # =========================
    TELEGRAM_BOT_TOKEN: str
    TELEGRAM_BOT_USERNAME: str

    # =========================
    # MAIL
    # =========================
    MAIL_USERNAME: str
    MAIL_PASSWORD: str
    MAIL_FROM: str
    MAIL_SERVER: str
    RESEND_API_KEY: str
    # =========================
    # CORS
    # =========================
    ALLOWED_ORIGINS: List[str] = []

    # =========================
    # SMS
    # =========================
    SMS_GATEWAY_URL: str

    # =========================
    # COOKIES
    # =========================
    COOKIE_DOMAIN: str = "localhost"
    COOKIE_SECURE: bool = False
    COOKIE_HTTPONLY: bool = True
    COOKIE_SAMESITE: str = "lax"

    # =========================
    # INTERNAL API
    # =========================
    INTERNAL_API_TOKEN: str

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="ignore",
    )

    # =========================
    # VALIDATORS
    # =========================
    @field_validator("ALLOWED_ORIGINS", mode="before")
    @classmethod
    def parse_origins(cls, v):
        if not v:
            return []
        if isinstance(v, str):
            try:
                return json.loads(v)
            except Exception:
                return [i.strip() for i in v.split(",")]
        return v

    @model_validator(mode="after")
    def validate_jwt_secret(self):
        if len(self.JWT_SECRET) < 32:
            raise ValueError("JWT_SECRET minimum 32 belgi bo'lishi kerak")
        return self

    # =========================
    # PROPERTIES
    # =========================
    @property
    def jwt_secret(self) -> str:
        return self.JWT_SECRET

    @property
    def telegram_token(self) -> str:
        return self.TELEGRAM_BOT_TOKEN

    @property
    def is_production(self) -> bool:
        return self.ENV == "production"


settings = Settings()
