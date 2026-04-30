# app/modules/billing/service.py
import uuid
import math
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.billing.models import (
    Plan,
    Subscription,
    Payment,
    SubscriptionRequest,
    PromoCode,
    PromoCodeUsage,
    SubscriptionStatus,
    SubscriptionRequestStatus,
    PaymentStatus,
    PaymentProvider,
    DiscountType,
    PlanInterval,
)
from app.modules.billing.schemas import (
    PlanCreate,
    PlanUpdate,
    SubscribeRequest,
    CancelRequest,
    ManualPaymentCreate,
    SubscriptionRequestCreate,
    SubscriptionRequestReview,
    PromoCodeCreate,
    PromoCodeUpdate,
)
from app.modules.auth.models import User


# ─── Plan slug → subscription tier xaritasi ──────────────────────────────────
# Plan slug lari: "free", "premium", "pro" va boshqalar
_PLAN_SLUG_TO_TIER: dict[str, str] = {
    "free": "FREE",
    "premium": "PREMIUM",
    "pro": "PRO",
    # Boshqa sluglar qo'shilsa shu yerga yoziladi
}


def _resolve_tier(plan: Plan) -> str:
    """Plan slug asosida subscription_tier qiymatini qaytaradi."""
    return _PLAN_SLUG_TO_TIER.get(plan.slug.lower(), "PREMIUM")


class BillingService:
    def __init__(self, db: AsyncSession):
        self.db = db

    def _now(self) -> datetime:
        return datetime.utcnow()

    # ════════════════════════════════════════════════════════════════
    # PLANS
    # ════════════════════════════════════════════════════════════════

    async def get_plans(self, only_active: bool = True) -> list[Plan]:
        stmt = select(Plan).order_by(Plan.sort_order, Plan.price)
        if only_active:
            stmt = stmt.where(Plan.is_active == True)
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def get_plan_by_slug(self, slug: str) -> Optional[Plan]:
        result = await self.db.execute(select(Plan).where(Plan.slug == slug))
        return result.scalar_one_or_none()

    async def get_plan_by_id(self, plan_id: uuid.UUID) -> Optional[Plan]:
        result = await self.db.execute(select(Plan).where(Plan.id == plan_id))
        return result.scalar_one_or_none()

    async def create_plan(self, data: PlanCreate) -> Plan:
        existing = await self.get_plan_by_slug(data.slug)
        if existing:
            raise ValueError(f"Slug '{data.slug}' already exists")
        plan = Plan(**data.model_dump())
        self.db.add(plan)
        await self.db.commit()
        await self.db.refresh(plan)
        return plan

    async def update_plan(self, plan_id: uuid.UUID, data: PlanUpdate) -> Plan:
        plan = await self.get_plan_by_id(plan_id)
        if not plan:
            raise ValueError("Plan not found")
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(plan, field, value)
        plan.updated_at = self._now()
        await self.db.commit()
        await self.db.refresh(plan)
        return plan

    async def delete_plan(self, plan_id: uuid.UUID) -> None:
        plan = await self.get_plan_by_id(plan_id)
        if not plan:
            raise ValueError("Plan not found")
        plan.is_active = False
        plan.updated_at = self._now()
        await self.db.commit()

    # ════════════════════════════════════════════════════════════════
    # PROMO CODES
    # ════════════════════════════════════════════════════════════════

    async def get_promo_code_by_code(self, code: str) -> Optional[PromoCode]:
        result = await self.db.execute(
            select(PromoCode).where(PromoCode.code == code.upper())
        )
        return result.scalar_one_or_none()

    async def get_promo_code_by_id(self, promo_id: uuid.UUID) -> Optional[PromoCode]:
        result = await self.db.execute(
            select(PromoCode).where(PromoCode.id == promo_id)
        )
        return result.scalar_one_or_none()

    async def create_promo_code(self, data: PromoCodeCreate) -> PromoCode:
        # Foiz chegirmasi 1–100 orasida bo'lishi kerak
        if data.discount_type == DiscountType.PERCENT and not (
            0 < data.discount_value <= 100
        ):
            raise ValueError("Foiz chegirmasi 1 dan 100 gacha bo'lishi kerak")

        existing = await self.get_promo_code_by_code(data.code)
        if existing:
            raise ValueError(f"'{data.code}' kodi allaqachon mavjud")

        payload = data.model_dump()
        payload["code"] = data.code.upper()
        if payload.get("valid_from") is None:
            payload["valid_from"] = self._now()

        promo = PromoCode(**payload)
        self.db.add(promo)
        await self.db.commit()
        await self.db.refresh(promo)
        return promo

    async def update_promo_code(
        self, promo_id: uuid.UUID, data: PromoCodeUpdate
    ) -> PromoCode:
        promo = await self.get_promo_code_by_id(promo_id)
        if not promo:
            raise ValueError("Promo kod topilmadi")
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(promo, field, value)
        promo.updated_at = self._now()
        await self.db.commit()
        await self.db.refresh(promo)
        return promo

    async def delete_promo_code(self, promo_id: uuid.UUID) -> None:
        promo = await self.get_promo_code_by_id(promo_id)
        if not promo:
            raise ValueError("Promo kod topilmadi")
        promo.is_active = False
        promo.updated_at = self._now()
        await self.db.commit()

    async def list_promo_codes(
        self,
        page: int = 1,
        size: int = 20,
        only_active: bool = False,
    ) -> dict:
        stmt = select(PromoCode).order_by(PromoCode.created_at.desc())
        if only_active:
            stmt = stmt.where(PromoCode.is_active == True)
        total = (
            await self.db.execute(select(func.count()).select_from(stmt.subquery()))
        ).scalar_one()
        items = (
            (await self.db.execute(stmt.offset((page - 1) * size).limit(size)))
            .scalars()
            .all()
        )
        return {
            "items": items,
            "total": total,
            "page": page,
            "size": size,
            "pages": math.ceil(total / size) if total else 0,
        }

    def _calc_discount(self, promo: PromoCode, original_price: float) -> float:
        """Chegirma miqdorini hisoblaydi."""
        if promo.discount_type == DiscountType.PERCENT:
            return round(original_price * promo.discount_value / 100, 2)
        # FIXED
        return min(promo.discount_value, original_price)

    async def _validate_promo(
        self,
        code: str,
        plan: Plan,
        user_id: uuid.UUID,
    ) -> PromoCode:
        """
        Promo kodni tekshiradi. Xato bo'lsa ValueError ko'taradi.
        To'g'ri bo'lsa PromoCode qaytaradi.
        """
        promo = await self.get_promo_code_by_code(code)
        if not promo:
            raise ValueError("Promo kod topilmadi")
        if not promo.is_active:
            raise ValueError("Promo kod faol emas")

        now = self._now()
        if promo.valid_from > now:
            raise ValueError("Promo kod hali kuchga kirmagan")
        if promo.valid_until and promo.valid_until < now:
            raise ValueError("Promo kod muddati tugagan")
        if promo.max_uses is not None and promo.uses_count >= promo.max_uses:
            raise ValueError("Promo kod ishlatish limiti tugagan")

        # Plan cheklovi
        if promo.plan_id and promo.plan_id != plan.id:
            raise ValueError("Bu promo kod ushbu plan uchun mos emas")

        # Bir foydalanuvchi bir marta
        if promo.one_per_user:
            used = await self.db.execute(
                select(PromoCodeUsage).where(
                    PromoCodeUsage.promo_code_id == promo.id,
                    PromoCodeUsage.user_id == user_id,
                )
            )
            if used.scalar_one_or_none():
                raise ValueError("Siz bu promo kodni allaqachon ishlatgansiz")

        return promo

    async def validate_promo_code(
        self, code: str, plan_slug: str, user_id: uuid.UUID
    ) -> dict:
        """
        Foydalanuvchiga promo kod natijasini qaytaradi (hali ishlatmaydi).
        """
        plan = await self.get_plan_by_slug(plan_slug)
        if not plan:
            raise ValueError("Plan topilmadi")

        try:
            promo = await self._validate_promo(code, plan, user_id)
            discount_amount = self._calc_discount(promo, plan.price)
            final_price = max(0.0, plan.price - discount_amount)
            return {
                "valid": True,
                "code": promo.code,
                "discount_type": promo.discount_type,
                "discount_value": promo.discount_value,
                "original_price": plan.price,
                "discount_amount": discount_amount,
                "final_price": final_price,
                "message": None,
            }
        except ValueError as e:
            return {
                "valid": False,
                "code": code.upper(),
                "discount_type": DiscountType.PERCENT,
                "discount_value": 0,
                "original_price": plan.price,
                "discount_amount": 0,
                "final_price": plan.price,
                "message": str(e),
            }

    async def _apply_promo(
        self,
        promo: PromoCode,
        user_id: uuid.UUID,
        plan: Plan,
        payment_id: Optional[uuid.UUID] = None,
        request_id: Optional[uuid.UUID] = None,
    ) -> float:
        """
        Promo kodni rasman ishlatadi:
        - uses_count oshiradi
        - PromoCodeUsage yozadi
        Chegirma miqdorini qaytaradi.
        """
        discount_amount = self._calc_discount(promo, plan.price)
        promo.uses_count += 1
        promo.updated_at = self._now()

        usage = PromoCodeUsage(
            promo_code_id=promo.id,
            user_id=user_id,
            payment_id=payment_id,
            subscription_request_id=request_id,
            discount_amount=discount_amount,
        )
        self.db.add(usage)
        return discount_amount

    # ════════════════════════════════════════════════════════════════
    # SUBSCRIPTIONS
    # ════════════════════════════════════════════════════════════════

    async def get_active_subscription(
        self, user_id: uuid.UUID
    ) -> Optional[Subscription]:
        now = self._now()
        result = await self.db.execute(
            select(Subscription)
            .options(selectinload(Subscription.plan))
            .where(
                Subscription.user_id == user_id,
                Subscription.status.in_(
                    [SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIAL]
                ),
                # Muddati o'tmagan yoki lifetime (end_date=NULL)
                or_(Subscription.end_date.is_(None), Subscription.end_date > now),
            )
            .order_by(Subscription.created_at.desc())
        )
        return result.scalars().first()

    async def get_user_subscriptions(self, user_id: uuid.UUID) -> list[Subscription]:
        result = await self.db.execute(
            select(Subscription)
            .options(selectinload(Subscription.plan))
            .where(Subscription.user_id == user_id)
            .order_by(Subscription.created_at.desc())
        )
        return result.scalars().all()

    def _calc_end_date(self, plan: Plan, now: datetime) -> Optional[datetime]:
        if plan.interval == PlanInterval.MONTHLY:
            return now + timedelta(days=30 * plan.interval_count)
        elif plan.interval == PlanInterval.YEARLY:
            return now + timedelta(days=365 * plan.interval_count)
        return None  # lifetime

    async def subscribe(
        self,
        user: User,
        data: SubscribeRequest,
    ) -> tuple[Subscription, Payment]:
        plan = await self.get_plan_by_slug(data.plan_slug)
        if not plan:
            raise ValueError("Plan topilmadi")
        if not plan.is_active:
            raise ValueError("Bu plan mavjud emas")

        # Promo kodni tekshirish
        promo: Optional[PromoCode] = None
        discount_amount = 0.0
        if data.promo_code:
            promo = await self._validate_promo(data.promo_code, plan, user.id)
            discount_amount = self._calc_discount(promo, plan.price)

        final_price = max(0.0, plan.price - discount_amount)

        # Mavjud aktiv obunani bekor qilish
        active = await self.get_active_subscription(user.id)
        if active:
            active.status = SubscriptionStatus.CANCELLED
            active.cancelled_at = self._now()
            active.cancel_reason = "Yangi planga o'tildi"
            active.updated_at = self._now()

        now = self._now()
        end_date = self._calc_end_date(plan, now)

        trial_end = None
        sub_status = SubscriptionStatus.ACTIVE
        if plan.trial_days > 0:
            trial_end = now + timedelta(days=plan.trial_days)
            sub_status = SubscriptionStatus.TRIAL

        subscription = Subscription(
            user_id=user.id,
            plan_id=plan.id,
            status=sub_status,
            start_date=now,
            end_date=end_date,
            trial_end_date=trial_end,
            auto_renew=data.auto_renew,
        )
        self.db.add(subscription)
        await self.db.flush()

        payment = Payment(
            user_id=user.id,
            subscription_id=subscription.id,
            plan_id=plan.id,
            amount=final_price,
            original_amount=plan.price,
            currency=plan.currency,
            status=PaymentStatus.PENDING,
            provider=data.provider,
            description=f"{plan.name} - obuna",
            promo_code_id=promo.id if promo else None,
            discount_amount=discount_amount,
        )
        self.db.add(payment)
        await self.db.flush()

        # Promo kodni rasman qo'llash
        if promo:
            await self._apply_promo(promo, user.id, plan, payment_id=payment.id)

        await self.db.commit()

        result = await self.db.execute(
            select(Subscription)
            .options(selectinload(Subscription.plan))
            .where(Subscription.id == subscription.id)
        )
        subscription = result.scalar_one()

        await self.db.refresh(payment)
        return subscription, payment

    async def cancel_subscription(
        self,
        user_id: uuid.UUID,
        data: CancelRequest,
    ) -> Subscription:
        sub = await self.get_active_subscription(user_id)
        if not sub:
            raise ValueError("Faol obuna topilmadi")
        sub.status = SubscriptionStatus.CANCELLED
        sub.cancelled_at = self._now()
        sub.cancel_reason = data.reason
        sub.auto_renew = False
        sub.updated_at = self._now()

        # Foydalanuvchi tierini FREE ga qaytarish
        user_result = await self.db.execute(
            select(User).where(User.id == user_id)
        )
        user_obj = user_result.scalar_one_or_none()
        if user_obj:
            user_obj.subscription_tier = "FREE"
            user_obj.subscription_tier_expires_at = None

        await self.db.commit()
        await self.db.refresh(sub)
        await self.db.refresh(sub, attribute_names=["plan"])
        return sub
    
    # ════════════════════════════════════════════════════════════════
    # SUBSCRIPTION REQUESTS  (screenshot / manual payment flow)
    # ════════════════════════════════════════════════════════════════

    async def create_subscription_request(
        self,
        user: User,
        data: SubscriptionRequestCreate,
    ) -> SubscriptionRequest:
        plan = await self.get_plan_by_slug(data.plan_slug)
        if not plan:
            raise ValueError("Plan topilmadi")
        if not plan.is_active:
            raise ValueError("Bu plan mavjud emas")

        # Kutilayotgan takroriy so'rov oldini olish
        existing = await self.db.execute(
            select(SubscriptionRequest).where(
                SubscriptionRequest.user_id == user.id,
                SubscriptionRequest.status == SubscriptionRequestStatus.PENDING,
            )
        )
        if existing.scalar_one_or_none():
            raise ValueError("Sizning kutilayotgan so'rovingiz allaqachon mavjud")

        # Promo kodni tekshirish
        promo: Optional[PromoCode] = None
        discount_amount = 0.0
        if data.promo_code:
            promo = await self._validate_promo(data.promo_code, plan, user.id)
            discount_amount = self._calc_discount(promo, plan.price)

        req = SubscriptionRequest(
            user_id=user.id,
            plan_id=plan.id,
            screenshot_url=data.screenshot_url,
            note=data.note,
            promo_code_id=promo.id if promo else None,
            discount_amount=discount_amount,
            original_amount=plan.price,
        )
        self.db.add(req)
        await self.db.flush()

        # Promo kodni rasman qo'llash
        if promo:
            await self._apply_promo(promo, user.id, plan, request_id=req.id)

        await self.db.commit()
        await self.db.refresh(req)
        await self.db.refresh(req, attribute_names=["plan"])
        return req

    async def get_my_requests(
        self, user_id: uuid.UUID, page: int = 1, size: int = 20
    ) -> dict:
        stmt = (
            select(SubscriptionRequest)
            .options(selectinload(SubscriptionRequest.plan))
            .where(SubscriptionRequest.user_id == user_id)
            .order_by(SubscriptionRequest.created_at.desc())
        )
        total = (
            await self.db.execute(select(func.count()).select_from(stmt.subquery()))
        ).scalar_one()
        items = (
            (await self.db.execute(stmt.offset((page - 1) * size).limit(size)))
            .scalars()
            .all()
        )
        return {
            "items": items,
            "total": total,
            "page": page,
            "size": size,
            "pages": math.ceil(total / size) if total else 0,
        }

    async def get_all_requests(
        self,
        page: int = 1,
        size: int = 20,
        status: Optional[SubscriptionRequestStatus] = None,
    ) -> dict:
        stmt = (
            select(SubscriptionRequest)
            .options(
                selectinload(SubscriptionRequest.plan),
                selectinload(SubscriptionRequest.user),
            )
            .order_by(SubscriptionRequest.created_at.desc())
        )
        if status:
            stmt = stmt.where(SubscriptionRequest.status == status)

        total = (
            await self.db.execute(select(func.count()).select_from(stmt.subquery()))
        ).scalar_one()
        items = (
            (await self.db.execute(stmt.offset((page - 1) * size).limit(size)))
            .scalars()
            .all()
        )
        return {
            "items": items,
            "total": total,
            "page": page,
            "size": size,
            "pages": math.ceil(total / size) if total else 0,
        }

    async def review_subscription_request(
        self,
        request_id: uuid.UUID,
        admin: User,
        data: SubscriptionRequestReview,
    ) -> SubscriptionRequest:
        """Admin so'rovni tasdiqlaydi yoki rad etadi."""
        result = await self.db.execute(
            select(SubscriptionRequest)
            .options(selectinload(SubscriptionRequest.plan))
            .where(SubscriptionRequest.id == request_id)
        )
        req = result.scalar_one_or_none()
        if not req:
            raise ValueError("So'rov topilmadi")
        if req.status != SubscriptionRequestStatus.PENDING:
            raise ValueError("So'rov allaqachon ko'rib chiqilgan")

        now = self._now()
        req.reviewed_by = admin.id
        req.reviewed_at = now
        req.updated_at = now

        if data.action == "approve":
            req.status = SubscriptionRequestStatus.APPROVED

            plan = req.plan
            active = await self.get_active_subscription(req.user_id)
            if active:
                active.status = SubscriptionStatus.CANCELLED
                active.cancelled_at = now
                active.cancel_reason = "Admin tasdiqlagan so'rov bilan almashtirildi"
                active.updated_at = now

            end_date = self._calc_end_date(plan, now)

            subscription = Subscription(
                user_id=req.user_id,
                plan_id=plan.id,
                status=SubscriptionStatus.ACTIVE,
                start_date=now,
                end_date=end_date,
                auto_renew=False,
            )
            self.db.add(subscription)
            await self.db.flush()

            # Chegirma hisobga olingan to'lov
            final_price = max(0.0, plan.price - req.discount_amount)

            payment = Payment(
                user_id=req.user_id,
                subscription_id=subscription.id,
                plan_id=plan.id,
                amount=final_price,
                original_amount=req.original_amount or plan.price,
                currency=plan.currency,
                status=PaymentStatus.COMPLETED,
                provider=PaymentProvider.MANUAL,
                description=f"Admin tasdiqlagan to'lov: {plan.name}",
                promo_code_id=req.promo_code_id,
                discount_amount=req.discount_amount,
                paid_at=now,
            )
            self.db.add(payment)
            req.subscription_id = subscription.id

            # ── Foydalanuvchi tierini yangilash ──────────────────────────
            user_result = await self.db.execute(
                select(User).where(User.id == req.user_id)
            )
            user_obj = user_result.scalar_one_or_none()
            if user_obj:
                user_obj.subscription_tier = _resolve_tier(plan)
                user_obj.subscription_tier_expires_at = end_date

        else:  # reject
            req.status = SubscriptionRequestStatus.REJECTED
            req.rejection_reason = data.rejection_reason

        await self.db.commit()
        await self.db.refresh(req)
        return req

    async def get_request_by_id(
        self, request_id: uuid.UUID
    ) -> Optional[SubscriptionRequest]:
        result = await self.db.execute(
            select(SubscriptionRequest)
            .options(selectinload(SubscriptionRequest.plan))
            .where(SubscriptionRequest.id == request_id)
        )
        return result.scalar_one_or_none()

    # ════════════════════════════════════════════════════════════════
    # PAYMENTS
    # ════════════════════════════════════════════════════════════════

    async def get_payments(
        self,
        user_id: uuid.UUID,
        page: int = 1,
        size: int = 20,
        status: Optional[PaymentStatus] = None,
    ) -> dict:
        stmt = select(Payment).where(Payment.user_id == user_id)
        if status:
            stmt = stmt.where(Payment.status == status)
        total = (
            await self.db.execute(select(func.count()).select_from(stmt.subquery()))
        ).scalar_one()
        stmt = (
            stmt.order_by(Payment.created_at.desc())
            .offset((page - 1) * size)
            .limit(size)
        )
        payments = (await self.db.execute(stmt)).scalars().all()
        return {
            "items": payments,
            "total": total,
            "page": page,
            "size": size,
            "pages": math.ceil(total / size) if total else 0,
        }

    async def get_payment_by_id(
        self,
        payment_id: uuid.UUID,
        user_id: Optional[uuid.UUID] = None,
    ) -> Optional[Payment]:
        stmt = select(Payment).where(Payment.id == payment_id)
        if user_id:
            stmt = stmt.where(Payment.user_id == user_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def confirm_payment(self, payment_id: uuid.UUID) -> Payment:
        payment = await self.get_payment_by_id(payment_id)
        if not payment:
            raise ValueError("To'lov topilmadi")
        if payment.status == PaymentStatus.COMPLETED:
            raise ValueError("To'lov allaqachon tasdiqlangan")

        payment.status = PaymentStatus.COMPLETED
        payment.paid_at = self._now()
        payment.updated_at = self._now()

        if payment.subscription_id:
            sub_result = await self.db.execute(
                select(Subscription).where(Subscription.id == payment.subscription_id)
            )
            sub = sub_result.scalar_one_or_none()
            if sub and sub.status != SubscriptionStatus.ACTIVE:
                sub.status = SubscriptionStatus.ACTIVE
                sub.updated_at = self._now()

        await self.db.commit()
        await self.db.refresh(payment)
        return payment

    async def create_manual_payment(self, data: ManualPaymentCreate) -> Payment:
        plan = await self.get_plan_by_slug(data.plan_slug)
        if not plan:
            raise ValueError("Plan topilmadi")
        payment = Payment(
            user_id=data.user_id,
            plan_id=plan.id,
            amount=data.amount,
            original_amount=data.amount,
            currency=data.currency,
            status=PaymentStatus.COMPLETED,
            provider=PaymentProvider.MANUAL,
            description=data.description or f"Manual: {plan.name}",
            paid_at=self._now(),
        )
        self.db.add(payment)
        await self.db.commit()
        await self.db.refresh(payment)
        return payment
