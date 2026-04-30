import uuid
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    AsyncSession,
    async_sessionmaker,
)
from sqlalchemy.orm import declarative_base
from sqlalchemy.types import TypeDecorator
from sqlalchemy.dialects.sqlite import CHAR

# ✅ FIX: settings dan import qilamiz — hardcode yo'q
from app.core.config import settings

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    future=True,
    # SQLite uchun zarur sozlama (PostgreSQL da e'tiborga olinmaydi)
    connect_args={"check_same_thread": False}
    if "sqlite" in settings.DATABASE_URL
    else {},
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

Base = declarative_base()


# ─── Markaziy UUID yordamchi ──────────────────────────────────────────────────
# billing, notifications va boshqa modullar shu bitta UUIDType ni ishlatadi.
# auth/models.py dagi sqlalchemy.types.Uuid bilan bir xil natija beradi.
class UUIDType(TypeDecorator):
    """UUID → 32-xonali hex string (SQLite va PostgreSQL bilan mos)."""

    impl = CHAR(32)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, uuid.UUID):
            return value.hex
        return uuid.UUID(str(value)).hex

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return uuid.UUID(value)


async def get_db() -> AsyncSession:  # type: ignore[return]
    async with AsyncSessionLocal() as session:
        try:
            yield session
            # ✅ NOTE: service lar o'z commit() larini chaqiradi.
            #    Bu yerda commit() ikkilamchi bo'lmasligi uchun
            #    faqat rollback saqlanadi — commit olib tashlandi.
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
