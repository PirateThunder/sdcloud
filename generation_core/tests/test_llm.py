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


def test_pathological_integer_literal_is_a_bounded_response_error():
    with pytest.raises(LLMResponseError, match="100 digits"):
        parse_json_response('{"value":' + "9" * 5000 + "}")


async def test_transport_failure_is_retried_without_using_repair_budget():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) < 3:
            raise httpx.ConnectError("connection lost", request=request)
        return response_with_content('{"ok": true}')

    llm = OpenAICompatibleLLM(
        model="local",
        base_url="http://vllm:8000/v1",
        transport=httpx.MockTransport(handler),
        request_retries=2,
        retry_delay=0,
    )
    try:
        assert await llm.chat_json("Return JSON", stage="brief") == {"ok": True}
    finally:
        await llm.close()
    assert len(requests) == 3


async def test_rate_limit_is_retried_but_client_schema_error_is_not():
    statuses = iter([429, 200, 400])
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        status = next(statuses)
        return response_with_content('{"ok": true}', status=status)

    llm = OpenAICompatibleLLM(
        model="local",
        base_url="http://vllm:8000/v1",
        transport=httpx.MockTransport(handler),
        request_retries=2,
        retry_delay=0,
    )
    try:
        assert await llm.chat_json("Return JSON", stage="brief") == {"ok": True}
        with pytest.raises(LLMError, match="HTTP 400") as exc_info:
            await llm.chat_json("Return JSON", stage="variables")
        assert exc_info.value.status_code == 400
    finally:
        await llm.close()
    assert len(requests) == 3


async def test_openrouter_retry_policy_is_configurable(monkeypatch):
    from pipeline.llm import OpenRouterLLM

    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return response_with_content('{"ok": true}')

    monkeypatch.setenv("LLM_REQUEST_RETRIES", "7")
    monkeypatch.setenv("LLM_RETRY_DELAY", "0.25")
    monkeypatch.setenv("OPENROUTER_PROVIDER_ORDER", "CoreWeave")
    monkeypatch.setenv("OPENROUTER_ALLOW_PROVIDER_FALLBACK", "0")
    llm = OpenRouterLLM(
        api_key="test",
        model="test-model",
        transport=httpx.MockTransport(handler),
    )
    try:
        assert llm.request_retries == 7
        assert llm.retry_delay == 0.25
        assert await llm.chat_json("prompt", stage="test") == {"ok": True}
        assert requests[0]["provider"] == {
            "order": ["CoreWeave"],
            "allow_fallbacks": False,
            "require_parameters": True,
        }
    finally:
        await llm.close()


async def test_empty_content_has_actionable_finish_reason():
    response = httpx.Response(
        200,
        json={"choices": [{"message": {"content": ""}, "finish_reason": "length"}]},
    )
    llm = OpenAICompatibleLLM(
        model="local",
        base_url="http://vllm:8000/v1",
        transport=httpx.MockTransport(lambda request: response),
    )
    try:
        with pytest.raises(LLMResponseError, match="finish_reason=length"):
            await llm.chat_json("Return JSON", stage="brief")
    finally:
        await llm.close()


async def test_truncated_json_reports_token_limit_and_preserves_excerpt():
    response = httpx.Response(
        200,
        json={
            "choices": [
                {"message": {"content": '{"variables": ['}, "finish_reason": "length"}
            ]
        },
    )
    llm = OpenAICompatibleLLM(
        model="local",
        base_url="http://vllm:8000/v1",
        transport=httpx.MockTransport(lambda request: response),
        max_tokens=123,
    )
    try:
        with pytest.raises(LLMResponseError, match="truncated.*max_tokens=123") as error:
            await llm.chat_json("Return JSON", stage="variables")
    finally:
        await llm.close()
    assert error.value.response_text == '{"variables": ['


def test_unquoted_numeric_arithmetic_is_safely_normalized():
    result = parse_json_response(
        '{"coefficient": 0.08 * 0.8, "scale": 1/3, "expression": "v^3/3"}'
    )
    assert result["coefficient"] == pytest.approx(0.064)
    assert result["scale"] == pytest.approx(1 / 3)
    assert result["expression"] == "v^3/3"


def test_arithmetic_normalization_rejects_code_and_invalid_numbers():
    for source in (
        '{"value": 1/3 + globals()}',
        '{"value": 1/0}',
        '{"value": 9999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999999}',
    ):
        with pytest.raises(LLMResponseError):
            parse_json_response(source)
