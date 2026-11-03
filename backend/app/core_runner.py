import asyncio
import time
from collections.abc import Awaitable, Callable

from .clients.generator import CoreJobInfo, GeneratorClient, GeneratorError


class CoreRunError(Exception):
    pass


def safe_core_error(raw: str | None, fallback: str) -> str:
    if not raw:
        return fallback
    first_line = raw.split("--- log tail ---", 1)[0].strip().splitlines()[0][:500]
    safe_prefixes = (
        "INVALID_",
        "UNSUPPORTED_",
        "MISSING_",
        "ModelValidationError",
        "SimulationError",
        "CLI exited",
    )
    return first_line if first_line.startswith(safe_prefixes) else fallback


async def submit_with_retry(submit: Callable[[], Awaitable[str]], timeout_seconds: int) -> str:
    deadline = time.monotonic() + timeout_seconds
    delay = 1.0
    while True:
        try:
            return await submit()
        except GeneratorError as exc:
            retriable_status = exc.status_code in {429, 500, 502, 503, 504}
            if (
                exc.status_code is not None and not retriable_status
            ) or time.monotonic() >= deadline:
                raise
            await asyncio.sleep(delay)
            delay = min(delay * 2, 10.0)


async def wait_for_core(
    client: GeneratorClient,
    job_id: str,
    *,
    timeout_seconds: int,
    poll_interval: float,
    heartbeat: Callable[[CoreJobInfo], Awaitable[None]],
    failure_message: str,
) -> CoreJobInfo:
    deadline = time.monotonic() + timeout_seconds
    while True:
        if time.monotonic() >= deadline:
            raise TimeoutError(f"core job exceeded {timeout_seconds} seconds")
        try:
            job = await client.get_job(job_id)
        except GeneratorError as exc:
            if exc.status_code is not None and exc.status_code not in {429, 500, 502, 503, 504}:
                raise
            await asyncio.sleep(min(poll_interval, 5.0))
            continue
        await heartbeat(job)
        if job.status == "done":
            return job
        if job.status == "error":
            raise CoreRunError(safe_core_error(job.error, failure_message))
        await asyncio.sleep(poll_interval)
