from fastapi import APIRouter
from sqlalchemy import text

from .database import DbDep
from .redis import RedisDep

router = APIRouter(tags=["system"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": "0.6.1"}


@router.get("/ready")
async def ready(db: DbDep, redis: RedisDep) -> dict[str, bool]:
    await db.execute(text("SELECT 1"))
    await redis.ping()
    return {"ready": True}
