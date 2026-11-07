from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from .exceptions import LLMError
from .llm import LLMClient, OpenAICompatibleLLM, OpenRouterLLM, _flag, _optional_integer

logger = logging.getLogger("pipeline.llm_routing")
_TRANSIENT_HTTP_STATUSES = {408, 409, 425, 429}


@dataclass(frozen=True)
class GPUMemory:
    index: int
    total_mib: int
    used_mib: int
    free_mib: int


class NvidiaSMIMonitor:
    def __init__(
        self,
        *,
        executable: str | None = None,
        ssh_target: str | None = None,
        ssh_port: int = 22,
        gpu_index: int = 0,
        timeout: float = 8,
    ) -> None:
        self.executable = executable or os.environ.get("LLM_VRAM_NVIDIA_SMI", "nvidia-smi")
        self.ssh_target = ssh_target
        self.ssh_port = ssh_port
        self.gpu_index = gpu_index
        self.timeout = timeout
        if gpu_index < 0:
            raise LLMError("LLM_VRAM_GPU_INDEX must be nonnegative")
        if not 1 <= ssh_port <= 65535:
            raise LLMError("LLM_VRAM_SSH_PORT must be a valid TCP port")

    def command(self) -> list[str]:
        query = [
            self.executable,
            f"--id={self.gpu_index}",
            "--query-gpu=memory.total,memory.used,memory.free",
            "--format=csv,noheader,nounits",
        ]
        if self.ssh_target:
            return [
                "ssh",
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=5",
                "-p",
                str(self.ssh_port),
                self.ssh_target,
                *query,
            ]
        return query

    async def read(self) -> GPUMemory:
        command = self.command()
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=self.timeout
            )
        except (OSError, TimeoutError) as exc:
            raise LLMError(
                "dynamic LLM routing could not query VRAM with nvidia-smi; "
                "configure LLM_VRAM_* or disable LLM_DYNAMIC_ROUTING"
            ) from exc
        if process.returncode != 0:
            detail = stderr.decode("utf-8", errors="replace")[:500]
            raise LLMError(f"dynamic LLM routing VRAM query failed: {detail}")
        try:
            total, used, free = (
                int(value.strip()) for value in stdout.decode("utf-8").strip().split(",")
            )
        except (ValueError, UnicodeDecodeError) as exc:
            raise LLMError("dynamic LLM routing received an invalid nvidia-smi response") from exc
        if total <= 0 or used < 0 or free < 0 or used + free > total:
            raise LLMError("dynamic LLM routing received inconsistent GPU memory values")
        return GPUMemory(self.gpu_index, total, used, free)


@dataclass(frozen=True)
class ModelTarget:
    role: str
    model: str
    base_url: str
    provider_name: str = "Local LLM"
    api_key: str | None = None
    cloud: bool = False
    max_tokens: int | None = None

    def create(self, *, transport: httpx.AsyncBaseTransport | None = None) -> LLMClient:
        if self.cloud:
            if not self.api_key:
                raise LLMError("OPENROUTER_API_KEY is required for dynamic cloud fallback")
            return OpenRouterLLM(
                api_key=self.api_key,
                model=self.model,
                base_url=self.base_url,
                transport=transport,
            )
        return OpenAICompatibleLLM(
            model=self.model,
            base_url=self.base_url,
            api_key=self.api_key,
            timeout=float(os.environ.get("LOCAL_LLM_TIMEOUT", "300")),
            provider_name=f"{self.provider_name} ({self.role})",
            structured_output=_flag("LOCAL_LLM_STRUCTURED_OUTPUT", True),
            allow_unstructured_fallback=_flag("LOCAL_LLM_ALLOW_UNSTRUCTURED_FALLBACK", False),
            max_tokens=(
                self.max_tokens
                if self.max_tokens is not None
                else int(os.environ.get("LOCAL_LLM_MAX_TOKENS", "4096"))
            ),
            seed=_optional_integer("LOCAL_LLM_SEED"),
            request_retries=int(os.environ.get("LLM_REQUEST_RETRIES", "2")),
            retry_delay=float(os.environ.get("LLM_RETRY_DELAY", "1")),
            transport=transport,
        )


@dataclass(frozen=True)
class RoutingDecision:
    role: str
    model: str
    provider: str
    free_vram_mib: int | None
    total_vram_mib: int | None
    threshold_mib: int
    fallback: bool
    attempts: tuple[dict[str, Any], ...]

    def log_entry(self) -> str:
        memory = (
            f"free_vram_mib={self.free_vram_mib}"
            if self.free_vram_mib is not None
            else "free_vram_mib=unavailable"
        )
        return (
            f"llm_route: role={self.role}; model={self.model}; provider={self.provider}; "
            f"{memory}; threshold_mib={self.threshold_mib}; fallback={str(self.fallback).lower()}; "
            f"failed_attempts={len(self.attempts)}"
        )


def is_transient_provider_error(error: LLMError) -> bool:
    if isinstance(error, LLMError) and type(error) is not LLMError:
        return False
    return error.status_code is None or error.status_code in _TRANSIENT_HTTP_STATUSES or (
        error.status_code >= 500
    )


class DynamicLLM:
    def __init__(
        self,
        large: ModelTarget,
        small: ModelTarget,
        *,
        monitor: NvidiaSMIMonitor,
        large_min_free_mib: int = 20_000,
        local_fallback: bool = True,
        cloud_fallback: bool = False,
        cloud_model: str | None = None,
        cloud_api_key: str | None = None,
        cloud_base_url: str = "https://openrouter.ai/api/v1",
    ) -> None:
        if large_min_free_mib < 0:
            raise LLMError("LLM_LARGE_MIN_FREE_MIB must be nonnegative")
        self.large = large
        self.small = small
        self.monitor = monitor
        self.large_min_free_mib = large_min_free_mib
        self.local_fallback = local_fallback
        self.cloud_fallback = cloud_fallback
        self.cloud_model = cloud_model
        self.cloud_api_key = cloud_api_key
        self.cloud_base_url = cloud_base_url
        self.last_decision: RoutingDecision | None = None

    @classmethod
    def from_env(cls) -> DynamicLLM:
        large_model = os.environ.get("LOCAL_LLM_LARGE_MODEL") or os.environ.get("LOCAL_LLM_MODEL")
        small_model = os.environ.get("LOCAL_LLM_SMALL_MODEL")
        if not large_model or not small_model:
            raise LLMError(
                "dynamic routing requires LOCAL_LLM_LARGE_MODEL and LOCAL_LLM_SMALL_MODEL"
            )
        ssh_target = os.environ.get("LLM_VRAM_SSH_TARGET") or None
        monitor = NvidiaSMIMonitor(
            ssh_target=ssh_target,
            ssh_port=int(os.environ.get("LLM_VRAM_SSH_PORT", "22")),
            gpu_index=int(os.environ.get("LLM_VRAM_GPU_INDEX", "0")),
        )

        def target_max_tokens(role: str) -> int:
            specific = os.environ.get(f"LOCAL_LLM_{role.upper()}_MAX_TOKENS")
            return int(specific or os.environ.get("LOCAL_LLM_MAX_TOKENS", "4096"))

        return cls(
            ModelTarget(
                "large",
                large_model,
                os.environ.get(
                    "LOCAL_LLM_LARGE_BASE_URL",
                    os.environ.get("LOCAL_LLM_BASE_URL", "http://127.0.0.1:8000/v1"),
                ),
                api_key=os.environ.get("LOCAL_LLM_LARGE_API_KEY")
                or os.environ.get("LOCAL_LLM_API_KEY")
                or None,
                max_tokens=target_max_tokens("large"),
            ),
            ModelTarget(
                "small",
                small_model,
                os.environ.get("LOCAL_LLM_SMALL_BASE_URL", "http://127.0.0.1:8001/v1"),
                api_key=os.environ.get("LOCAL_LLM_SMALL_API_KEY")
                or os.environ.get("LOCAL_LLM_API_KEY")
                or None,
                max_tokens=target_max_tokens("small"),
            ),
            monitor=monitor,
            large_min_free_mib=int(os.environ.get("LLM_LARGE_MIN_FREE_MIB", "20000")),
            local_fallback=_flag("LLM_DYNAMIC_LOCAL_FALLBACK", True),
            cloud_fallback=_flag("LLM_DYNAMIC_CLOUD_FALLBACK", False),
            cloud_model=os.environ.get("LLM_DYNAMIC_CLOUD_MODEL")
            or os.environ.get("OPENROUTER_MODEL"),
            cloud_api_key=os.environ.get("OPENROUTER_API_KEY"),
            cloud_base_url=os.environ.get(
                "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"
            ),
        )

    async def route_operation[T](
        self,
        operation: Callable[[LLMClient, RoutingDecision], Awaitable[T]],
    ) -> T:
        memory: GPUMemory | None = None
        memory_error: LLMError | None = None
        try:
            memory = await self.monitor.read()
        except LLMError as exc:
            memory_error = exc
            if not self.cloud_fallback:
                raise
            logger.warning("VRAM unavailable; explicitly configured cloud fallback will be used")
        roles = ["cloud"] if memory is None else [
            "large" if memory.free_mib >= self.large_min_free_mib else "small"
        ]
        if memory is not None and self.local_fallback:
            roles.append("small" if roles[0] == "large" else "large")
        if self.cloud_fallback:
            roles.append("cloud")
        attempts: list[dict[str, Any]] = []
        if memory_error is not None:
            attempts.append({"role": "vram", "error": str(memory_error)[:500]})
        for role in dict.fromkeys(roles):
            try:
                if role == "cloud":
                    if not self.cloud_model:
                        raise LLMError("LLM_DYNAMIC_CLOUD_MODEL is required for cloud fallback")
                    target = ModelTarget(
                        "cloud",
                        self.cloud_model,
                        self.cloud_base_url,
                        provider_name="OpenRouter",
                        api_key=self.cloud_api_key,
                        cloud=True,
                    )
                else:
                    target = getattr(self, role)
                client = target.create()
            except LLMError as exc:
                attempts.append({"role": role, "error": str(exc)[:500]})
                if role == roles[-1]:
                    raise
                continue
            decision = RoutingDecision(
                role=role,
                model=target.model,
                provider=target.provider_name,
                free_vram_mib=memory.free_mib if memory else None,
                total_vram_mib=memory.total_mib if memory else None,
                threshold_mib=self.large_min_free_mib,
                fallback=any(item["role"] in {"vram", "large", "small", "cloud"} for item in attempts),
                attempts=tuple(attempts),
            )
            logger.info("selected %s", decision.log_entry())
            try:
                result = await operation(client, decision)
            except LLMError as exc:
                attempts.append(
                    {"role": role, "model": target.model, "error": str(exc)[:500]}
                )
                exc.routing_attempts = tuple(attempts)
                if not is_transient_provider_error(exc):
                    raise
                if role == roles[-1]:
                    raise
                logger.warning(
                    "transient provider failure on %s (%s); restarting the whole operation on %s",
                    target.model,
                    str(exc)[:300],
                    roles[roles.index(role) + 1],
                )
            else:
                self.last_decision = decision
                return result
            finally:
                await client.close()
        raise AssertionError("dynamic LLM route list is empty")

    async def chat_json(
        self,
        prompt: str,
        *,
        stage: str,
        system: str | None = None,
        temperature: float = 0.3,
        response_schema: dict | None = None,
    ) -> Any:
        async def call(client: LLMClient, decision: RoutingDecision) -> Any:
            return await client.chat_json(
                prompt,
                stage=stage,
                system=system,
                temperature=temperature,
                response_schema=response_schema,
            )

        return await self.route_operation(call)

    async def close(self) -> None:
        return None


def routing_from_document(document: Any) -> dict[str, Any] | None:
    from .io import read_json

    entry = next(
        (item for item in reversed(document.generation_log) if item.startswith("llm_route: ")),
        None,
    )
    if entry is None:
        return None
    values = {}
    for item in entry.removeprefix("llm_route: ").split("; "):
        key, value = item.split("=", 1)
        values[key] = (
            int(value)
            if value.isdigit()
            else value == "true"
            if value in {"true", "false"}
            else value
        )
    if document.artifacts.get("routing"):
        path = Path(document.artifacts["routing"])
        if path.is_file():
            values["attempts"] = read_json(path)["attempts"]
    return values


def write_routing_trace(workdir: Path | None, decision: RoutingDecision) -> str | None:
    if workdir is None:
        return None
    from .io import write_json_atomic

    path = workdir / "routing.json"
    write_json_atomic(
        path,
        {
            "schema_version": "1.0",
            "role": decision.role,
            "model": decision.model,
            "provider": decision.provider,
            "free_vram_mib": decision.free_vram_mib,
            "total_vram_mib": decision.total_vram_mib,
            "threshold_mib": decision.threshold_mib,
            "fallback": decision.fallback,
            "attempts": decision.attempts,
        },
    )
    return str(path)


async def generate_with_routing[T](
    llm: LLMClient,
    operation: Callable[..., Awaitable[T]],
    *args: Any,
    workdir: Path | None = None,
    **kwargs: Any,
) -> T:
    if not isinstance(llm, DynamicLLM):
        return await operation(*args, llm, workdir=workdir, **kwargs)

    async def run(client: LLMClient, decision: RoutingDecision) -> T:
        attempt_workdir = (
            workdir / f"attempt_{len(decision.attempts) + 1}_{decision.role}"
            if workdir is not None
            else None
        )
        result = await operation(*args, client, workdir=attempt_workdir, **kwargs)
        write_routing_trace(workdir, decision)
        if hasattr(result, "generation_log"):
            result = result.model_copy(
                update={"generation_log": [*result.generation_log, decision.log_entry()]}
            )
        elif getattr(result, "model", None) is not None:
            model = result.model
            result = result.model_copy(
                update={
                    "model": model.model_copy(
                        update={
                            "generation_log": [
                                *model.generation_log,
                                decision.log_entry(),
                            ]
                        }
                    )
                }
            )
        return result

    return await llm.route_operation(run)
