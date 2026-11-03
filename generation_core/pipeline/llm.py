import json
import os
import re
from copy import deepcopy
from pathlib import Path
from typing import Any, Protocol

import httpx

from .exceptions import LLMError


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


def parse_json_response(text: str) -> Any:
    stripped = text.strip()
    block = re.search(r"```(?:json)?\s*\n?(.*?)```", stripped, re.DOTALL)
    if block:
        stripped = block.group(1).strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError as original:
        for pattern in (r"(\[.*\])", r"(\{.*\})"):
            match = re.search(pattern, stripped, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(1))
                except json.JSONDecodeError:
                    continue
        raise LLMError(f"failed to parse LLM JSON: {original}") from original


class OpenRouterLLM:
    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        base_url: str = "https://openrouter.ai/api/v1",
        timeout: float = 120.0,
        proxy: str | None = None,
    ) -> None:
        self.model = model
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
            proxy=proxy,
            trust_env=False,
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
        }
        if response_schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "sdcloud_response",
                    "strict": True,
                    "schema": response_schema,
                },
            }
        try:
            response = await self._client.post("/chat/completions", json=payload)
            if response.is_error and response_schema is not None:
                payload.pop("response_format", None)
                response = await self._client.post("/chat/completions", json=payload)
            response.raise_for_status()
            body = response.json()
            content = body["choices"][0]["message"]["content"]
            if not isinstance(content, str):
                raise LLMError(f"OpenRouter returned non-text content at stage {stage}")
            return parse_json_response(content)
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
            raise LLMError(f"OpenRouter request failed at stage {stage}: {exc}") from exc

    async def close(self) -> None:
        await self._client.aclose()


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
