import asyncio

import pytest

from pipeline.exceptions import LLMError, LLMResponseError, ModelValidationError
from pipeline.generation import generate_model
from pipeline.llm import create_llm
from pipeline.routing import (
    DynamicLLM,
    GPUMemory,
    ModelTarget,
    NvidiaSMIMonitor,
    generate_with_routing,
    is_transient_provider_error,
    routing_from_document,
)
from pipeline.schemas import ConversationResponse


class StaticMonitor:
    def __init__(self, free=24000, error=None):
        self.free = free
        self.error = error
        self.calls = 0

    async def read(self):
        self.calls += 1
        if self.error:
            raise self.error
        return GPUMemory(0, 24463, 24463 - self.free, self.free)


class StubLLM:
    def __init__(self, response=None, error=None):
        self.response = response if response is not None else {"ok": True}
        self.error = error
        self.calls = []
        self.closed = False

    async def chat_json(self, prompt, *, stage, **kwargs):
        self.calls.append((stage, prompt))
        if self.error:
            raise self.error
        return self.response

    async def close(self):
        self.closed = True


@pytest.fixture(autouse=True)
def restore_model_target_factory():
    original = ModelTarget.create
    yield
    ModelTarget.create = original


def router(monitor, large, small, **kwargs):
    cloud_client = kwargs.pop("cloud_client", None)
    dynamic = DynamicLLM(
        ModelTarget("large", "large-model", "http://large/v1"),
        ModelTarget("small", "small-model", "http://small/v1"),
        monitor=monitor,
        **kwargs,
    )
    clients = {"large": large, "small": small, "cloud": cloud_client}
    original_create = ModelTarget.create

    def create(target, **create_kwargs):
        if clients.get(target.role) is not None:
            return clients[target.role]
        return original_create(target, **create_kwargs)

    import pipeline.routing as routing_module

    routing_module.ModelTarget.create = create
    return dynamic


async def test_high_vram_selects_large_once_per_operation():
    large, small = StubLLM(), StubLLM()
    llm = router(StaticMonitor(free=23000), large, small)
    result = await llm.chat_json("hello", stage="brief")
    assert result == {"ok": True}
    assert large.calls[0][0] == "brief"
    assert small.calls == []
    assert llm.last_decision.role == "large"
    assert llm.last_decision.free_vram_mib == 23000


async def test_constrained_vram_selects_small():
    large, small = StubLLM(), StubLLM()
    llm = router(StaticMonitor(free=7000), large, small)
    await llm.chat_json("hello", stage="brief")
    assert large.calls == []
    assert small.calls[0][0] == "brief"
    assert llm.last_decision.role == "small"


async def test_transient_failure_restarts_operation_on_small_and_records_reason():
    large = StubLLM(error=LLMError("HTTP 503", status_code=503))
    small = StubLLM()
    llm = router(StaticMonitor(), large, small)
    result = await llm.chat_json("hello", stage="components")
    assert result == {"ok": True}
    assert len(large.calls) == 1
    assert len(small.calls) == 1
    assert large.closed and small.closed
    assert llm.last_decision.fallback is True
    assert llm.last_decision.attempts[0]["role"] == "large"
    assert "503" in llm.last_decision.attempts[0]["error"]


@pytest.mark.parametrize(
    "error",
    [
        LLMError("schema rejected", status_code=400),
        LLMResponseError("malformed JSON"),
        ModelValidationError("invalid equation"),
    ],
)
async def test_non_provider_errors_never_change_model(error):
    large = StubLLM(error=error)
    small = StubLLM()
    llm = router(StaticMonitor(), large, small)
    with pytest.raises(type(error)):
        await llm.chat_json("hello", stage="equations")
    assert len(large.calls) == 1
    assert small.calls == []


async def test_small_failure_can_retry_large_but_does_not_hide_final_failure():
    large = StubLLM()
    small = StubLLM(error=LLMError("HTTP 500", status_code=500))
    llm = router(StaticMonitor(free=7000), large, small)
    assert await llm.chat_json("hello", stage="brief") == {"ok": True}
    assert llm.last_decision.role == "large"
    assert llm.last_decision.fallback is True

    large.error = LLMError("HTTP 500", status_code=500)
    small.error = LLMError("HTTP 500", status_code=500)
    with pytest.raises(LLMError, match="HTTP 500") as caught:
        await llm.chat_json("hello", stage="brief")
    assert len(caught.value.routing_attempts) == 2


async def test_cloud_requires_explicit_opt_in_when_vram_is_unavailable():
    large, small = StubLLM(), StubLLM()
    monitor = StaticMonitor(error=LLMError("nvidia-smi unavailable"))
    llm = router(monitor, large, small)
    with pytest.raises(LLMError, match="unavailable"):
        await llm.chat_json("hello", stage="brief")

    cloud = StubLLM()
    llm = router(
        monitor,
        large,
        small,
        cloud_fallback=True,
        cloud_model="cloud-model",
        cloud_client=cloud,
    )
    await llm.chat_json("hello", stage="brief")
    assert cloud.calls[0][0] == "brief"
    assert llm.last_decision.role == "cloud"
    assert llm.last_decision.fallback is True
    assert llm.last_decision.free_vram_mib is None


async def test_generation_fallback_restarts_all_stages_and_keeps_trace(
    generation_request, fixture_llm, monkeypatch, tmp_path
):
    large = StubLLM(error=LLMError("HTTP 503", status_code=503))
    monitor = StaticMonitor()
    import pipeline.routing as routing_module

    def create(target, **kwargs):
        return large if target.role == "large" else fixture_llm

    monkeypatch.setattr(routing_module.ModelTarget, "create", create)
    llm = DynamicLLM(
        ModelTarget("large", "large-model", "http://large/v1"),
        ModelTarget("small", "small-model", "http://small/v1"),
        monitor=monitor,
    )
    document = await generate_model(generation_request, llm, workdir=tmp_path)
    assert document.validation.status == "passed"
    assert any("role=small" in item for item in document.generation_log)
    assert routing_from_document(document)["fallback"] is True
    assert (tmp_path / "routing.json").is_file()
    assert (tmp_path / "attempt_1_large" / "stage.json").is_file()
    assert (tmp_path / "attempt_2_small" / "stage.json").is_file()
    assert large.calls[0][0] == "brief"
    assert (tmp_path / "attempt_2_small" / "brief_response.json").is_file()


async def test_factory_dynamic_routing_is_opt_in(monkeypatch):
    monkeypatch.setenv("LOCAL_LLM_MODEL", "large-model")
    monkeypatch.setenv("LOCAL_LLM_SMALL_MODEL", "small-model")
    monkeypatch.setenv("LOCAL_LLM_BASE_URL", "http://large/v1")
    monkeypatch.setenv("LOCAL_LLM_SMALL_BASE_URL", "http://small/v1")
    monkeypatch.setenv("LLM_DYNAMIC_ROUTING", "0")
    normal = create_llm("local")
    assert normal.model == "large-model"
    await normal.close()
    monkeypatch.setenv("LLM_DYNAMIC_ROUTING", "1")
    monkeypatch.setenv("LOCAL_LLM_LARGE_MAX_TOKENS", "2048")
    monkeypatch.setenv("LOCAL_LLM_SMALL_MAX_TOKENS", "4096")
    dynamic = create_llm("local")
    assert isinstance(dynamic, DynamicLLM)
    assert dynamic.large.max_tokens == 2048
    assert dynamic.small.max_tokens == 4096
    await dynamic.close()


async def test_nvidia_smi_parser_and_ssh_command(monkeypatch):
    monitor = NvidiaSMIMonitor(
        executable="/usr/lib/wsl/lib/nvidia-smi", ssh_target="gpu-host", ssh_port=2222
    )
    command = monitor.command()
    assert command[:3] == ["ssh", "-o", "BatchMode=yes"]
    assert "gpu-host" in command
    assert command[-2] == "--query-gpu=memory.total,memory.used,memory.free"

    class Process:
        returncode = 0

        async def communicate(self):
            return b"24463, 185, 24278\n", b""

    async def fake_exec(*args, **kwargs):
        return Process()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    memory = await monitor.read()
    assert memory.free_mib == 24278
    assert memory.total_mib == 24463


def test_transient_classification_is_conservative():
    assert is_transient_provider_error(LLMError("network")) is True
    assert is_transient_provider_error(LLMError("bad", status_code=400)) is False
    assert is_transient_provider_error(LLMResponseError("bad JSON")) is False


async def test_conversation_model_keeps_selected_route(generation_request, fixture_llm, tmp_path):
    document = await generate_model(generation_request, fixture_llm)
    response = ConversationResponse(kind="model", assistant_text="Готово", model=document)
    llm = router(StaticMonitor(), StubLLM(), StubLLM())

    async def operation(request, client, *, workdir, **kwargs):
        return response

    routed = await generate_with_routing(llm, operation, generation_request, workdir=tmp_path)
    assert routed.model is not None
    assert any("role=large" in item for item in routed.model.generation_log)
    assert (tmp_path / "routing.json").is_file()
