import pytest

from app.clients.generator import GeneratorError
from app.core_runner import safe_core_error, submit_with_retry, wait_for_core
from tests.helpers import core_job


async def test_submit_retries_only_temporary_errors(monkeypatch):
    async def no_sleep(delay):
        return None

    monkeypatch.setattr("app.core_runner.asyncio.sleep", no_sleep)
    attempts = 0

    async def submit():
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise GeneratorError("unavailable")
        return "job-1"

    assert await submit_with_retry(submit, 10) == "job-1"
    assert attempts == 3

    attempts = 0

    async def invalid():
        nonlocal attempts
        attempts += 1
        raise GeneratorError("bad request", 422)

    with pytest.raises(GeneratorError):
        await submit_with_retry(invalid, 10)
    assert attempts == 1


async def test_wait_for_core_recovers_from_transport_error(monkeypatch):
    async def no_sleep(delay):
        return None

    monkeypatch.setattr("app.core_runner.asyncio.sleep", no_sleep)
    calls = 0
    heartbeats = 0

    class Client:
        async def get_job(self, job_id):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise GeneratorError("temporary")
            return core_job(job_id, "simulate")

    async def heartbeat(job):
        nonlocal heartbeats
        heartbeats += 1

    result = await wait_for_core(
        Client(),
        "job-1",
        timeout_seconds=10,
        poll_interval=0,
        heartbeat=heartbeat,
        failure_message="failed",
    )
    assert result.status == "done"
    assert calls == 2
    assert heartbeats == 1


def test_core_errors_do_not_expose_internal_log_tail():
    assert (
        safe_core_error("RuntimeError: /private/path\n--- log tail ---\nprompt", "failed")
        == "failed"
    )
    assert safe_core_error(
        "INVALID_TIME_GRID: bad step\n--- log tail ---\nprompt", "failed"
    ).startswith("INVALID_TIME_GRID")
