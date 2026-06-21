"""Async OpenRouter LLM client.

Under the hood delegates blocking calls to UniversalAI (litellm + OpenAI SDK)
so that the FastAPI event loop is not blocked.
"""

import asyncio
import json
import re
from typing import Optional

from app.core.config import settings
from app.core.exceptions import LLMError

from .universal_ai import AIResponse, UniversalAI


class OpenRouterLLM:
    """Async adapter around the synchronous UniversalAI client."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        timeout: float = 120.0,
    ) -> None:
        self.api_key = api_key or settings.openrouter_api_key
        self.model = model or settings.openrouter_model
        self.timeout = timeout
        self._client: UniversalAI | None = None

    def _get_client(self) -> UniversalAI:
        if self._client is None:
            self._client = UniversalAI(
                api_key=self.api_key,
                default_text_model=self.model,
            )
        return self._client

    async def chat(
        self,
        prompt: str,
        system: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs,
    ) -> AIResponse:
        """Send a chat completion request to OpenRouter asynchronously."""
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(
                    self._get_client().chat,
                    prompt,
                    system=system,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    **kwargs,
                ),
                timeout=self.timeout,
            )
        except asyncio.TimeoutError as exc:
            raise LLMError(detail="OpenRouter request timed out") from exc
        except Exception as exc:
            error_msg = str(exc)
            # Surface common LiteLLM / OpenAI errors cleanly.
            if "Authentication" in error_msg or "incorrect API key" in error_msg:
                raise LLMError(detail="OpenRouter authentication failed") from exc
            raise LLMError(detail=f"OpenRouter request error: {error_msg}") from exc

    async def chat_with_json_output(
        self,
        prompt: str,
        system: Optional[str] = None,
        temperature: float = 0.4,
        max_tokens: int | None = None,
        **kwargs,
    ) -> dict:
        """Send a chat request and parse the response as JSON."""
        response = await self.chat(
            prompt=prompt,
            system=system,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )

        if response.text is None:
            raise LLMError(detail="Empty response from LLM")

        # Try to extract JSON from markdown code blocks
        text = response.text.strip()
        json_match = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
        if json_match:
            text = json_match.group(1).strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            # Try to find JSON array/object directly in text
            array_match = re.search(r"(\[.*\])", text, re.DOTALL)
            if array_match:
                try:
                    return json.loads(array_match.group(1))
                except json.JSONDecodeError:
                    pass
            object_match = re.search(r"(\{.*\})", text, re.DOTALL)
            if object_match:
                try:
                    return json.loads(object_match.group(1))
                except json.JSONDecodeError:
                    pass
            raise LLMError(
                detail=f"Failed to parse LLM response as JSON: {str(exc)}"
            ) from exc

    async def close(self) -> None:
        """No-op for the adapter; sync client is closed on garbage collection."""
        self._client = None

    async def __aenter__(self) -> "OpenRouterLLM":
        return self

    async def __aexit__(self, *exc_info) -> None:
        await self.close()
