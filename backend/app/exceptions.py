import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)


class ApiError(HTTPException):
    pass


class NotFoundError(ApiError):
    def __init__(self, detail: str = "resource not found") -> None:
        super().__init__(404, detail)


class ConflictError(ApiError):
    def __init__(self, detail: str) -> None:
        super().__init__(409, detail)


async def redis_unavailable_handler(request: Request, exc: RedisError) -> JSONResponse:
    logger.warning("Redis is unavailable on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=503, content={"detail": "temporary service unavailability"})


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "internal server error"})


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(RedisError, redis_unavailable_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
