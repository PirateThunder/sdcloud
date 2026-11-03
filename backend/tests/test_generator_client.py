import httpx
import pytest

from app.clients.generator import GeneratorClient, GeneratorError


async def test_client_sends_idempotency_and_retries_transport(monkeypatch):
    calls = []

    async def no_sleep(delay):
        return None

    monkeypatch.setattr("app.clients.generator.asyncio.sleep", no_sleep)

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) < 3:
            raise httpx.ConnectError("temporary", request=request)
        return httpx.Response(202, json={"job_id": "job-1", "status": "pending"})

    client = GeneratorClient(
        base_url="http://core", api_key="secret", transport=httpx.MockTransport(handler)
    )
    job_id = await client.create_chat({"description": "test"}, "generation-1")
    assert job_id == "job-1"
    assert len(calls) == 3
    assert calls[-1].url.path == "/api/v1/chat"
    assert calls[-1].headers["x-api-key"] == "secret"
    assert calls[-1].headers["idempotency-key"] == "generation-1"
    await client.close()


async def test_client_rejects_malformed_core_result():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=["not", "an", "object"])

    client = GeneratorClient(base_url="http://core", transport=httpx.MockTransport(handler))
    with pytest.raises(GeneratorError, match="unexpected JSON"):
        await client.get_result("job-1")
    await client.close()
