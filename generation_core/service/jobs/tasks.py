import asyncio
import contextlib
import logging
import os
import resource
import signal

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ..broker import broker
from ..config import ROOT, Settings, get_settings
from . import service
from .models import Job
from .schemas import JobKind, JobStatus

logger = logging.getLogger("service.jobs")
_SEMAPHORE = asyncio.Semaphore(get_settings().worker_concurrency)


def timeout_for_job(settings: Settings, kind: str) -> int:
    if kind == JobKind.SIMULATE.value:
        return settings.simulation_timeout
    if kind == JobKind.IMPORT.value:
        return settings.import_timeout
    return settings.job_timeout


def _apply_limits(settings: Settings, timeout: int) -> None:
    resource.setrlimit(resource.RLIMIT_CPU, (timeout, timeout + 5))
    memory = settings.job_memory_mb * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
    output_size = settings.job_max_file_mb * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_FSIZE, (output_size, output_size))
    resource.setrlimit(resource.RLIMIT_NOFILE, (settings.job_max_files, settings.job_max_files))


@broker.task
async def run_job(job_id: str) -> None:
    await execute_job(job_id)


async def execute_job(
    job_id: str,
    *,
    session: AsyncSession | None = None,
    settings: Settings | None = None,
) -> None:
    settings = settings or get_settings()
    if session is not None:
        await _execute_with_session(session, settings, job_id)
        return
    engine = create_async_engine(settings.database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as own_session:
            await _execute_with_session(own_session, settings, job_id)
    finally:
        await engine.dispose()


async def _execute_with_session(session: AsyncSession, settings: Settings, job_id: str) -> None:
    try:
        async with _SEMAPHORE:
            job = await session.get(Job, job_id)
            if job is None or job.status != JobStatus.PENDING.value:
                return
            argv = service.load_argv(settings, job)
            if argv is None:
                raise RuntimeError("missing or invalid argv.json")
            directory = service.job_dir(settings, job_id)
            timeout = timeout_for_job(settings, job.kind)
            job.status = JobStatus.RUNNING.value
            job.stage = "subprocess"
            job.started_at = service.now()
            job.error = None
            await session.commit()

            with (directory / "job.log").open("w", encoding="utf-8") as log:
                process = await asyncio.create_subprocess_exec(
                    *argv,
                    cwd=ROOT,
                    stdout=log,
                    stderr=asyncio.subprocess.STDOUT,
                    env={
                        **os.environ,
                        "PYTHONUNBUFFERED": "1",
                        "OPENBLAS_NUM_THREADS": "1",
                        "OMP_NUM_THREADS": "1",
                        "MKL_NUM_THREADS": "1",
                        "NUMEXPR_NUM_THREADS": "1",
                    },
                    start_new_session=True,
                    preexec_fn=lambda: _apply_limits(settings, timeout),
                )
                try:
                    returncode = await asyncio.wait_for(process.wait(), timeout=timeout)
                except TimeoutError:
                    with contextlib.suppress(ProcessLookupError):
                        os.killpg(process.pid, signal.SIGKILL)
                    await process.wait()
                    returncode = -9

            job.returncode = returncode
            job.finished_at = service.now()
            expected = directory / service.result_name(service.JobKind(job.kind))
            if returncode == 0 and expected.is_file():
                job.status = JobStatus.DONE.value
                job.stage = "done"
                job.manifest = service.read_manifest(settings, job)
            else:
                job.status = JobStatus.ERROR.value
                job.stage = "error"
                tail = service.log_tail(settings, job, 40)
                job.error = f"CLI exited with code {returncode}\n--- log tail ---\n{tail}"
            await session.commit()
    except Exception as exc:
        logger.exception("job %s failed", job_id)
        await session.rollback()
        job = await session.get(Job, job_id)
        if job is not None:
            job.status = JobStatus.ERROR.value
            job.stage = "error"
            job.error = f"{type(exc).__name__}: {exc}"[:2000]
            job.finished_at = service.now()
            await session.commit()


async def dispatch(job_id: str) -> None:
    await run_job.kiq(job_id)
