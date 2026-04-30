# app/modules/notifications/sms_service.py

import os
import re
import asyncio
from datetime import datetime, timedelta
from typing import Optional

import httpx

from app.core.config import settings


class SmsService:
    LOGIN_URL = "https://notify.eskiz.uz/api/auth/login"
    SMS_URL = "https://notify.eskiz.uz/api/message/sms/send"

    LOGIN_EMAIL = os.environ.get("ESKIZ_EMAIL", "kholikulovelyor@gmail.com")
    LOGIN_PASSWORD = os.environ.get("ESKIZ_PASSWORD", "lWMS8DpghTyKoxHalY8Rvi8OocKFLxYx4pWBSL9f")

    def __init__(self):
        self._token: Optional[str] = None
        self._token_expires_at: Optional[datetime] = None
        self._lock = asyncio.Lock()

    # =====================================================
    # 🔒 PHONE NORMALIZE
    # =====================================================

    def _normalize_phone(self, phone: str) -> str:
        phone = re.sub(r"\D", "", phone)

        if phone.startswith("998") and len(phone) == 12:
            return phone

        raise ValueError("Invalid phone format (expected 998XXXXXXXXX)")

    # =====================================================
    # 🔑 TOKEN (SAFE + LOCKED)
    # =====================================================

    async def _get_token(self) -> str:
        async with self._lock:
            if (
                self._token
                and self._token_expires_at
                and self._token_expires_at > datetime.utcnow()
            ):
                return self._token

            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(
                    self.LOGIN_URL,
                    data={
                        "email": settings.ESKIZ_EMAIL,
                        "password": settings.ESKIZ_PASSWORD,
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )

            if response.status_code != 200:
                raise Exception(f"Eskiz login failed: {response.text}")

            data = response.json()
            token = data.get("data", {}).get("token")

            if not token:
                raise Exception("Eskiz token not found")

            self._token = token
            self._token_expires_at = datetime.utcnow() + timedelta(hours=23)

            return token

    # =====================================================
    # 📩 SEND SMS (RETRY + SAFE)
    # =====================================================

    async def send_sms(
        self,
        phone: str,
        message: str,
        *,
        retries: int = 2,
    ) -> None:
        phone = self._normalize_phone(phone)

        if len(message) > 160:
            raise ValueError("SMS too long")

        token = await self._get_token()

        payload = {
            "mobile_phone": phone,
            "message": message,
            "from": settings.SMS_FROM or "4546",
        }

        headers = {
            "Authorization": f"Bearer {token}",
        }

        for attempt in range(retries + 1):
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    response = await client.post(
                        self.SMS_URL,
                        json=payload,
                        headers=headers,
                    )

                if response.status_code == 200:
                    return

                # token expired → retry once with new token
                if response.status_code == 401 and attempt == 0:
                    self._token = None
                    token = await self._get_token()
                    continue

                raise Exception(response.text)

            except Exception as e:
                if attempt == retries:
                    raise Exception(f"SMS send failed: {str(e)}")
                await asyncio.sleep(1)
