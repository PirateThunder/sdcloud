"""sdCloud FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.exceptions import (
    AppException,
    AuthenticationError,
    AuthorizationError,
    ConflictError,
    LLMError,
    NotFoundError,
    SimulationError,
    ValidationError,
)
from app.db.session import close_db, init_db

# Configure logging
logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler — startup and shutdown."""
    # Startup
    logger.info("Starting up sdCloud backend...")
    logger.info("Initializing database tables...")
    try:
        await init_db()
        logger.info("Database tables initialized.")
    except Exception as exc:
        logger.warning(f"Could not initialize tables (may already exist): {exc}")

    yield

    # Shutdown
    logger.info("Shutting down sdCloud backend...")
    await close_db()
    logger.info("Database connections closed.")


def create_application() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="AI-powered system dynamics modeling platform",
        debug=settings.debug,
        lifespan=lifespan,
    )

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include API routers
    app.include_router(api_router)

    # Global exception handlers
    @app.exception_handler(AppException)
    async def handle_app_exception(request, exc: AppException):
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
        )

    @app.exception_handler(AuthenticationError)
    async def handle_auth_error(request, exc: AuthenticationError):
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
            headers=exc.headers,
        )

    @app.exception_handler(AuthorizationError)
    async def handle_authz_error(request, exc: AuthorizationError):
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
        )

    @app.exception_handler(NotFoundError)
    async def handle_not_found(request, exc: NotFoundError):
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
        )

    @app.exception_handler(ConflictError)
    async def handle_conflict(request, exc: ConflictError):
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
        )

    @app.exception_handler(ValidationError)
    async def handle_validation(request, exc: ValidationError):
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
        )

    @app.exception_handler(LLMError)
    async def handle_llm_error(request, exc: LLMError):
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
        )

    @app.exception_handler(SimulationError)
    async def handle_sim_error(request, exc: SimulationError):
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
        )

    return app


# Create the application instance
app = create_application()


@app.get("/", include_in_schema=False)
async def root() -> dict:
    """Root endpoint — API info."""
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "docs": "/docs",
        "health": "/api/v1/health",
    }
