from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .auth.router import router as auth_router
from .config import get_settings
from .conversations.router import router as conversations_router
from .database import engine
from .exceptions import register_exception_handlers
from .generations.router import router as generations_router
from .models.router import router as models_router
from .redis import get_redis
from .simulations.router import router as simulations_router
from .system import router as system_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await get_redis().aclose()
    await engine.dispose()


settings = get_settings()
app_kwargs = {
    "title": "sdCloud Backend",
    "version": "0.2.1",
    "description": "Email/OTP authentication, conversations, system dynamics models and simulations",
    "lifespan": lifespan,
}
if settings.env not in {"local", "staging", "test"}:
    app_kwargs["openapi_url"] = None

app = FastAPI(**app_kwargs)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
register_exception_handlers(app)
app.include_router(system_router)
app.include_router(auth_router, prefix="/api/v1")
app.include_router(conversations_router, prefix="/api/v1")
app.include_router(generations_router, prefix="/api/v1")
app.include_router(models_router, prefix="/api/v1")
app.include_router(simulations_router, prefix="/api/v1")
