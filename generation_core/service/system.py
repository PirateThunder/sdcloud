from fastapi import APIRouter
from sqlalchemy import text

from version import VERSION

from .database import DbDep

router = APIRouter(tags=["system"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": VERSION}


@router.get("/ready")
async def ready(db: DbDep) -> dict[str, bool]:
    await db.execute(text("SELECT 1"))
    return {"ready": True}
