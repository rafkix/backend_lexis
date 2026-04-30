import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select

from app.core.config import settings
from app.core.database import init_db, AsyncSessionLocal
from app.modules.auth.models import Role
from app.modules.auth import auth_router
from app.modules.users import users_router
from app.modules.notifications import not_router
from app.modules.billing import billing_router
from app.modules.ielts_reading import ielts_router


# ══════════════════════════════════════════════════════════════════════
# LIFESPAN
# ══════════════════════════════════════════════════════════════════════


async def _seed_roles() -> None:
    """Ensure default roles exist in the database."""
    async with AsyncSessionLocal() as db:
        for name, desc in [
            ("USER", "Default user"),
            ("ADMIN", "System administrator"),
        ]:
            result = await db.execute(select(Role).where(Role.name == name))
            if not result.scalar_one_or_none():
                db.add(Role(name=name, description=desc))
        await db.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    print("✅ Database initialized.")
    await _seed_roles()
    print("✅ Default roles seeded.")
    yield
    # Shutdown: kerak bo'lsa bu yerga cleanup yoziladi

app = FastAPI(
    title="Lexis Backend API",
    version="1.0.0",
    lifespan=lifespan,
    description=(
        "Lexis is an AI-powered speaking practice platform designed for IELTS and CEFR preparation.\n"
        "It simulates real exam conditions, analyzes speech in real-time, and provides instant feedback "
        "on fluency, vocabulary, grammar, and pronunciation.\n"
        "The API manages users, speaking sessions, AI scoring, progress tracking, and performance analytics."
    ),
)

# ══════════════════════════════════════════════════════════════════════
# MIDDLEWARE
# ══════════════════════════════════════════════════════════════════════

origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "https://lexis.uz",
    "https://app.lexis.uz",
    "https://api.lexis.uz",
    *settings.ALLOWED_ORIGINS,
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(set(origins)),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)

app.add_middleware(
    SessionMiddleware,
    secret_key=settings.JWT_SECRET,
)

# ══════════════════════════════════════════════════════════════════════
# STATIC FILES
# ══════════════════════════════════════════════════════════════════════

os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

# ══════════════════════════════════════════════════════════════════════
# ROUTERS
# ══════════════════════════════════════════════════════════════════════

API_PREFIX = "/api/v1"

for r in [
    auth_router,
    users_router,
    not_router,
    billing_router,
    ielts_router,
]:
    app.include_router(r, prefix=API_PREFIX)

# ══════════════════════════════════════════════════════════════════════
# EXCEPTION HANDLERS
# ══════════════════════════════════════════════════════════════════════


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "status_code": exc.status_code,
                "detail": exc.detail,
                "path": str(request.url),
            }
        },
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    print(f"❌ Unexpected error: {exc}")
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "status_code": 500,
                "detail": "Internal Server Error",
                "path": str(request.url),
            }
        },
    )


# ══════════════════════════════════════════════════════════════════════
# HEALTH
# ══════════════════════════════════════════════════════════════════════


@app.get("/", tags=["System"], include_in_schema=False)
async def root():
    return {
        "message": "🚀 Lexis Backend API is running!",
        "version": "1.0.0",
        "docs": "/docs",
        "redoc": "/redoc",
    }


@app.get("/health", tags=["System"])
async def health_check():
    return {"status": "ok", "database": "connected"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
