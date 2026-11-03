import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from service.config import Settings, get_settings
from service.jobs.models import Job
from service.jobs.schemas import JobStatus
from service.jobs.tasks import timeout_for_job

logger = logging.getLogger("service.watchdog")


async def mark_stale_jobs(
    session: AsyncSession,
    settings: Settings,
    *,
    current_time: datetime | None = None,
) -> list[str]:
    current_time = current_time or datetime.now(UTC)
    jobs = list(
        (
            await session.scalars(
                select(Job).where(
                    or_(
                        Job.status == JobStatus.PENDING.value,
                        Job.status == JobStatus.RUNNING.value,
                    )
                )
            )
        ).all()
    )
    stale = []
    for job in jobs:
        timeout = timeout_for_job(settings, job.kind)
        if job.status == JobStatus.PENDING.value:
            reference = job.created_at
            limit = timeout * 2 + settings.stale_grace_seconds
        else:
            reference = job.started_at or job.created_at
            limit = timeout + settings.stale_grace_seconds
        if reference.tzinfo is None:
            reference = reference.replace(tzinfo=UTC)
        if reference <= current_time - timedelta(seconds=limit):
            previous_status = job.status
            job.status = JobStatus.ERROR.value
            job.stage = "error"
            job.error = f"STALE_JOB: job exceeded {limit} seconds in {previous_status}"
            job.finished_at = current_time
            stale.append(job.id)
    if stale:
        await session.commit()
    return stale


async def main() -> None:
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        while True:
            try:
                async with factory() as session:
                    stale = await mark_stale_jobs(session, settings)
                    if stale:
                        logger.warning("marked stale jobs: %s", stale)
            except Exception:
                logger.exception("watchdog sweep failed")
            await asyncio.sleep(settings.watchdog_interval)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
