from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from service.config import Settings
from service.jobs.models import Job
from service.jobs.schemas import JobStatus
from service.models import Base
from watchdog import mark_stale_jobs


async def test_watchdog_marks_only_stale_jobs(tmp_path):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime.now(UTC)
    async with factory() as session:
        stale = Job(
            id="stale",
            kind="generate",
            status=JobStatus.RUNNING.value,
            request={},
            request_hash="x",
            attempt=1,
            created_at=now - timedelta(hours=1),
            started_at=now - timedelta(hours=1),
        )
        fresh = Job(
            id="fresh",
            kind="generate",
            status=JobStatus.RUNNING.value,
            request={},
            request_hash="y",
            attempt=1,
            created_at=now,
            started_at=now,
        )
        session.add_all([stale, fresh])
        await session.commit()
        marked = await mark_stale_jobs(session, Settings(jobs_root=tmp_path), current_time=now)
        assert marked == ["stale"]
        assert stale.status == JobStatus.ERROR.value
        assert "STALE_JOB" in stale.error
        assert fresh.status == JobStatus.RUNNING.value
    await engine.dispose()
