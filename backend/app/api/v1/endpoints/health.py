"""Health check endpoint."""

import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db

router = APIRouter(tags=["Health"])


@router.get(
    "/health",
    summary="Health check — database connectivity",
)
async def health_check(db: AsyncSession = Depends(get_db)) -> dict:
    """
    Check the health of the application and its dependencies.

    Returns status of:
    - Application itself
    - PostgreSQL database connectivity
    """
    checks = {
        "app": {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()},
        "database": {"status": "unknown"},
    }

    # Check database
    try:
        start = datetime.now(timezone.utc)
        await db.execute(text("SELECT 1"))
        elapsed = (datetime.now(timezone.utc) - start).total_seconds()
        checks["database"] = {
            "status": "ok",
            "response_time_ms": round(elapsed * 1000, 2),
        }
    except Exception as exc:
        checks["database"] = {
            "status": "error",
            "detail": str(exc),
        }

    # Overall status
    all_ok = all(c["status"] == "ok" for c in checks.values())

    return {
        "status": "healthy" if all_ok else "unhealthy",
        "checks": checks,
    }


@router.get(
    "/ready",
    summary="Readiness probe",
)
async def readiness_check(db: AsyncSession = Depends(get_db)) -> dict:
    """Kubernetes-style readiness probe."""
    try:
        await db.execute(text("SELECT 1"))
        return {"ready": True}
    except Exception:
        return {"ready": False}


@router.get(
    "/live",
    summary="Liveness probe",
)
async def liveness_check() -> dict:
    """Kubernetes-style liveness probe."""
    return {"alive": True}
