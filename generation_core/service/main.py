from fastapi import Depends, FastAPI

from version import VERSION

from .auth import verify_api_key
from .config import get_settings
from .exceptions import register_exception_handlers
from .jobs import router as jobs_router
from .system import router as system_router

app_kwargs = {
    "title": "sdCloud Generation Core API",
    "version": VERSION,
    "description": "CLI-first system dynamics generation and simulation service",
}
if get_settings().environment not in {"local", "staging"}:
    app_kwargs["openapi_url"] = None

app = FastAPI(**app_kwargs)
register_exception_handlers(app)
app.include_router(system_router)
app.include_router(jobs_router, prefix="/api/v1", dependencies=[Depends(verify_api_key)])
