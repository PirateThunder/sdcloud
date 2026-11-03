import json

import httpx
import pytest

from pipeline.exceptions import LLMError, LLMResponseError
from pipeline.llm import OpenAICompatibleLLM, create_llm, parse_json_response


def response_with_content(content: str, status: int = 200) -> httpx.Response:
    if status != 200:
        return httpx.Response(status, json={"error": {"message": "schema rejected"}})
    return httpx.Response(
        status,
        json={"choices": [{"message": {"role": "assistant", "content": content}}]},
    )


async def test_local_provider_sends_structured_output_without_api_key():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return response_with_content('{"ok": true}')

    llm = OpenAICompatibleLLM(
        model="Qwen/Qwen3-32B",
        base_url="http://vllm:8000/v1",
        transport=httpx.MockTransport(handler),
        max_tokens=1234,
    )
    try:
        result = await llm.chat_json(
            "Return JSON",
            stage="brief",
            response_schema={
                "type": "object",
                "properties": {
                    "ok": {"type": "boolean"},
                    "count": {"type": "integer", "default": 1},
                },
                "required": ["ok"],
                "additionalProperties": False,
            },
        )
    finally:
        await llm.close()
    assert result == {"ok": True}
    assert "authorization" not in requests[0].headers
    payload = json.loads(requests[0].content)
    assert payload["model"] == "Qwen/Qwen3-32B"
    assert payload["max_tokens"] == 1234
    assert payload["response_format"]["type"] == "json_schema"
    schema = payload["response_format"]["json_schema"]["schema"]
    assert schema["required"] == ["ok", "count"]
    assert "default" not in schema["properties"]["count"]


async def test_structured_output_failure_does_not_silently_fallback():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return response_with_content("", status=400)

    llm = OpenAICompatibleLLM(
        model="local",
        base_url="http://vllm:8000/v1",
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(LLMError, match="HTTP 400"):
            await llm.chat_json(
                "Return JSON",
                stage="variables",
                response_schema={"type": "object"},
            )
    finally:
        await llm.close()
    assert calls == 1


async def test_explicit_unstructured_fallback_is_opt_in():
    payloads = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        payloads.append(payload)
        if "response_format" in payload:
            return response_with_content("", status=400)
        return response_with_content('{"ok": true}')

    llm = OpenAICompatibleLLM(
        model="local",
        base_url="http://vllm:8000/v1",
        transport=httpx.MockTransport(handler),
        allow_unstructured_fallback=True,
    )
    try:
        result = await llm.chat_json(
            "Return JSON", stage="brief", response_schema={"type": "object"}
        )
    finally:
        await llm.close()
    assert result == {"ok": True}
    assert len(payloads) == 2
    assert "response_format" not in payloads[1]


async def test_local_factory_requires_model_but_not_api_key(monkeypatch):
    monkeypatch.setenv("LOCAL_LLM_BASE_URL", "http://vllm:8000/v1")
    monkeypatch.delenv("LOCAL_LLM_API_KEY", raising=False)
    monkeypatch.delenv("LOCAL_LLM_MODEL", raising=False)
    with pytest.raises(LLMError, match="LOCAL_LLM_MODEL"):
        create_llm("local")
    monkeypatch.setenv("LOCAL_LLM_MODEL", "Qwen/Qwen3-32B")
    llm = create_llm("vllm")
    try:
        assert llm.model == "Qwen/Qwen3-32B"
    finally:
        await llm.close()


def test_malformed_json_contains_repair_context():
    with pytest.raises(LLMResponseError) as error:
        parse_json_response("{broken")
    assert error.value.response_text == "{broken"
