import asyncio
import json
import os
import re
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from pathlib import Path
from typing import Any, Protocol

import httpx

from .exceptions import LLMError, LLMResponseError, ModelValidationError
from .expression_parser import normalize_expression

_INFERENCE_SEED: ContextVar[int | None] = ContextVar("inference_seed", default=None)


@contextmanager
def use_inference_seed(seed: int | None):
    token = _INFERENCE_SEED.set(seed)
    try:
        yield
    finally:
        _INFERENCE_SEED.reset(token)


class LLMClient(Protocol):
    async def chat_json(
        self,
        prompt: str,
        *,
        stage: str,
        system: str | None = None,
        temperature: float = 0.3,
        response_schema: dict | None = None,
    ) -> Any: ...

    async def close(self) -> None: ...


def _limited_integer(value: str) -> int:
    if len(value.lstrip("-")) > 100:
        raise ValueError("integer literal exceeds 100 digits")
    return int(value)


def _json_loads(text: str) -> Any:
    return json.loads(text, parse_int=_limited_integer)


def _normalize_unquoted_arithmetic(text: str) -> str:
    pattern = re.compile(r"(:[ \t]*)([-+*/^%().\d eE\t]+?)(?=[ \t]*[,}\]\n])")

    def replace(match: re.Match[str]) -> str:
        candidate = match.group(2).strip()
        if len(candidate) > 200 or not any(operator in candidate for operator in "+-*/%^"):
            return match.group(0)
        try:
            expression = normalize_expression(candidate)
            value = expression.get("value")
            if expression.get("op") != "lit" or isinstance(value, bool):
                return match.group(0)
            if not isinstance(value, int | float):
                return match.group(0)
            return f"{match.group(1)}{json.dumps(value, allow_nan=False)}"
        except (ModelValidationError, ArithmeticError, TypeError, ValueError):
            return match.group(0)

    return pattern.sub(replace, text)


def parse_json_response(text: str) -> Any:
    stripped = text.strip()
    block = re.search(r"```(?:json)?\s*\n?(.*?)```", stripped, re.DOTALL)
    if block:
        stripped = block.group(1).strip()
    try:
        return _json_loads(stripped)
    except ValueError as original:
        repaired = _normalize_unquoted_arithmetic(stripped)
        if repaired != stripped:
            try:
                return _json_loads(repaired)
            except ValueError:
                pass
        for pattern in (r"(\[.*\])", r"(\{.*\})"):
            match = re.search(pattern, stripped, re.DOTALL)
            if match:
                try:
                    return _json_loads(match.group(1))
                except ValueError:
                    continue
        raise LLMResponseError(
            f"failed to parse LLM JSON: {original}", response_text=stripped[:6000]
        ) from original


def _flag(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _optional_integer(name: str) -> int | None:
    value = os.environ.get(name)
    return int(value) if value not in {None, ""} else None


def strict_json_schema(value: Any) -> Any:
    if isinstance(value, list):
        return [strict_json_schema(item) for item in value]
    if not isinstance(value, dict):
        return value
    result = {
        key: strict_json_schema(item)
        for key, item in value.items()
        if key != "default"
    }
    properties = result.get("properties")
    if isinstance(properties, dict):
        result["required"] = list(properties)
    return result


class OpenAICompatibleLLM:
    def __init__(
        self,
        model: str,
        *,
        base_url: str,
        api_key: str | None = None,
        timeout: float = 120.0,
        proxy: str | None = None,
        provider_name: str = "OpenAI-compatible",
        structured_output: bool = True,
        allow_unstructured_fallback: bool = False,
        max_tokens: int = 8192,
        seed: int | None = None,
        request_retries: int = 2,
        retry_delay: float = 1.0,
        transport: httpx.AsyncBaseTransport | None = None,
        provider_options: dict | None = None,
    ) -> None:
        self.model = model
        self.provider_name = provider_name
        self.provider_options = deepcopy(provider_options) if provider_options else {}
        self.structured_output = structured_output
        self.component_structured_output = _flag("LLM_COMPONENT_STRUCTURED_OUTPUT", False)
        self.pattern_shortcut = _flag("LLM_PATTERN_SHORTCUT", False)
        self.allow_unstructured_fallback = allow_unstructured_fallback
        self.max_tokens = max_tokens
        self.seed = seed
        self.request_retries = max(0, request_retries)
        self.retry_delay = retry_delay
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers=headers,
            timeout=timeout,
            proxy=proxy,
            trust_env=False,
            transport=transport,
        )

    async def chat_json(
        self,
        prompt: str,
        *,
        stage: str,
        system: str | None = None,
        temperature: float = 0.3,
        response_schema: dict | None = None,
    ) -> Any:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": self.max_tokens,
        }
        if self.provider_options:
            payload["provider"] = deepcopy(self.provider_options)
        seed = _INFERENCE_SEED.get()
        if seed is None:
            seed = self.seed
        if seed is not None:
            payload["seed"] = seed
        if response_schema is not None and self.structured_output:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "sdcloud_response",
                    "strict": True,
                    "schema": strict_json_schema(response_schema),
                },
            }

        async def post() -> httpx.Response:
            for attempt in range(self.request_retries + 1):
                try:
                    response = await self._client.post("/chat/completions", json=payload)
                except httpx.HTTPError:
                    if attempt >= self.request_retries:
                        raise
                else:
                    transient = response.status_code in {408, 409, 425, 429} or response.status_code >= 500
                    if not transient or attempt >= self.request_retries:
                        return response
                await asyncio.sleep(self.retry_delay * (2**attempt))
            raise AssertionError("unreachable")

        try:
            response = await post()
            if (
                response.is_error
                and response_schema is not None
                and self.allow_unstructured_fallback
            ):
                payload.pop("response_format", None)
                response = await post()
            if response.is_error:
                raise LLMError(
                    f"{self.provider_name} HTTP {response.status_code} at stage {stage}: "
                    f"{response.text[:1000]}",
                    status_code=response.status_code,
                )
            try:
                body = response.json()
            except ValueError as exc:
                raise LLMResponseError(
                    f"{self.provider_name} returned invalid response JSON at stage {stage}",
                    response_text=response.text[:6000],
                ) from exc
            if not isinstance(body, dict) or not isinstance(body.get("choices"), list) or not body["choices"]:
                raise LLMResponseError(
                    f"{self.provider_name} response has no choices at stage {stage}: "
                    f"{response.text[:1000]}",
                    response_text=response.text[:6000],
                )
            choice = body["choices"][0]
            content = choice["message"]["content"]
            if not isinstance(content, str) or not content.strip():
                finish_reason = choice.get("finish_reason", "unknown")
                raise LLMResponseError(
                    f"{self.provider_name} returned empty content at stage {stage}; "
                    f"finish_reason={finish_reason}",
                    response_text=content if isinstance(content, str) else "",
                )
            try:
                return parse_json_response(content)
            except LLMResponseError as exc:
                if choice.get("finish_reason") == "length":
                    raise LLMResponseError(
                        f"{self.provider_name} response truncated at stage {stage}: "
                        f"finish_reason=length, max_tokens={self.max_tokens}. "
                        "Return concise JSON without repeated assumptions.",
                        response_text=exc.response_text,
                    ) from exc
                raise
        except LLMError:
            raise
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
            raise LLMError(f"{self.provider_name} request failed at stage {stage}: {exc}") from exc

    async def close(self) -> None:
        await self._client.aclose()


class OpenRouterLLM(OpenAICompatibleLLM):
    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        base_url: str = "https://openrouter.ai/api/v1",
        timeout: float = 120.0,
        proxy: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(
            model=model,
            base_url=base_url,
            api_key=api_key,
            timeout=timeout,
            proxy=proxy,
            provider_name="OpenRouter",
            structured_output=_flag("LLM_STRUCTURED_OUTPUT", True),
            allow_unstructured_fallback=_flag("LLM_ALLOW_UNSTRUCTURED_FALLBACK", False),
            max_tokens=int(os.environ.get("LLM_MAX_TOKENS", "8192")),
            seed=_optional_integer("LLM_SEED"),
            request_retries=int(os.environ.get("LLM_REQUEST_RETRIES", "5")),
            retry_delay=float(os.environ.get("LLM_RETRY_DELAY", "2")),
            transport=transport,
            provider_options=(
                {
                    "order": [
                        item.strip()
                        for item in os.environ["OPENROUTER_PROVIDER_ORDER"].split(",")
                        if item.strip()
                    ],
                    "allow_fallbacks": _flag("OPENROUTER_ALLOW_PROVIDER_FALLBACK", False),
                    "require_parameters": True,
                }
                if os.environ.get("OPENROUTER_PROVIDER_ORDER")
                else None
            ),
        )
        self.component_structured_output = _flag("LLM_COMPONENT_STRUCTURED_OUTPUT", False)
        self.pattern_shortcut = _flag("LLM_PATTERN_SHORTCUT", False)


class FixtureLLM:
    def __init__(self, path: Path) -> None:
        try:
            self._responses = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise LLMError(f"cannot load LLM fixture {path}: {exc}") from exc

    async def chat_json(
        self,
        prompt: str,
        *,
        stage: str,
        system: str | None = None,
        temperature: float = 0.3,
        response_schema: dict | None = None,
    ) -> Any:
        if stage not in self._responses:
            raise LLMError(f"LLM fixture has no response for stage {stage}")
        response = self._responses[stage]
        if isinstance(response, list):
            for candidate in response:
                if candidate.get("contains", "") in prompt:
                    return deepcopy(candidate["response"])
            raise LLMError(f"LLM fixture has no matching response for stage {stage}")
        return deepcopy(response)

    async def close(self) -> None:
        return None


def create_llm(provider: str, fixture_path: Path | None = None) -> LLMClient:
    if provider == "fixture":
        if fixture_path is None:
            raise LLMError("fixture provider requires --fixture or LLM_FIXTURE_PATH")
        return FixtureLLM(fixture_path)
    if provider in {"local", "vllm", "openai_compatible"}:
        if _flag("LLM_DYNAMIC_ROUTING", False):
            from .routing import DynamicLLM

            return DynamicLLM.from_env()
        model = os.environ.get("LOCAL_LLM_MODEL")
        if not model:
            raise LLMError("LOCAL_LLM_MODEL is required for the local provider")
        return OpenAICompatibleLLM(
            model=model,
            base_url=os.environ.get("LOCAL_LLM_BASE_URL", "http://127.0.0.1:8000/v1"),
            api_key=os.environ.get("LOCAL_LLM_API_KEY") or None,
            timeout=float(os.environ.get("LOCAL_LLM_TIMEOUT", "300")),
            provider_name="Local LLM",
            structured_output=_flag("LOCAL_LLM_STRUCTURED_OUTPUT", True),
            allow_unstructured_fallback=_flag("LOCAL_LLM_ALLOW_UNSTRUCTURED_FALLBACK", False),
            max_tokens=int(os.environ.get("LOCAL_LLM_MAX_TOKENS", "8192")),
            seed=_optional_integer("LOCAL_LLM_SEED"),
        )
    if provider != "openrouter":
        raise LLMError(f"unknown LLM provider: {provider}")
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise LLMError("OPENROUTER_API_KEY is required for the openrouter provider")
    return OpenRouterLLM(
        api_key=api_key,
        model=os.environ.get("OPENROUTER_MODEL", "openai/gpt-4o-mini"),
        base_url=os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
        proxy=os.environ.get("PROXY_URL") or None,
    )
