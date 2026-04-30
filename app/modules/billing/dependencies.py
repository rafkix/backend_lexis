# app/modules/billing/dependencies.py
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.modules.billing.service import BillingService

async def get_billing_service(
    db: AsyncSession = Depends(get_db),
) -> BillingService:
    return BillingService(db)
