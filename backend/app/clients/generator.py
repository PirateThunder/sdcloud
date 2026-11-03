import asyncio
from datetime import datetime
from typing import Literal

import httpx
from pydantic import BaseModel, Field, ValidationError

from ..config import get_settings


class GeneratorError(Exception):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class CoreJobCreated(BaseModel):
    job_id: str
    status: str


class CoreJobInfo(BaseModel):
    job_id: str
    kind: str
    status: Literal["pending", "running", "done", "error"]
    stage: str | None = None
    attempt: int
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    files: list[str] = Field(default_factory=list)
    manifest: dict | None = None
    error: str | None = None


class GeneratorClient:
    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        settings = get_settings()
        key = api_key if api_key is not None else settings.generator_api_key
        self._client = httpx.AsyncClient(
            base_url=base_url or settings.generator_url,
            headers={"X-API-Key": key} if key else {},
            timeout=httpx.Timeout(60.0, connect=10.0, read=60.0),
            transport=transport,
            trust_env=False,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        delay = 0.5
        for attempt in range(3):
            try:
                response = await self._client.request(method, path, **kwargs)
            except httpx.TransportError as exc:
                if attempt == 2:
                    raise GeneratorError("generator is unavailable") from exc
                await asyncio.sleep(delay)
                delay *= 2
                continue
            if response.status_code < 400:
                return response
            if response.status_code not in {408, 425, 429, 500, 502, 503, 504} or attempt == 2:
                raise GeneratorError(
                    f"generator returned HTTP {response.status_code}", response.status_code
                )
            await asyncio.sleep(delay)
            delay *= 2
        raise GeneratorError("generator request failed")

    @staticmethod
    def _json(response: httpx.Response) -> dict:
        try:
            value = response.json()
        except (ValueError, UnicodeDecodeError) as exc:
            raise GeneratorError("generator returned malformed JSON") from exc
        if not isinstance(value, dict):
            raise GeneratorError("generator returned an unexpected JSON value")
        return value

    async def create_model(self, payload: dict, idempotency_key: str) -> str:
        response = await self._request(
            "POST",
            "/api/v1/models",
            json=payload,
            headers={"Idempotency-Key": idempotency_key},
        )
        try:
            return CoreJobCreated.model_validate(self._json(response)).job_id
        except ValidationError as exc:
            raise GeneratorError("generator returned an invalid job") from exc

    async def create_chat(self, payload: dict, idempotency_key: str) -> str:
        response = await self._request(
            "POST",
            "/api/v1/chat",
            json=payload,
            headers={"Idempotency-Key": idempotency_key},
        )
        try:
            return CoreJobCreated.model_validate(self._json(response)).job_id
        except ValidationError as exc:
            raise GeneratorError("generator returned an invalid job") from exc

    async def create_simulation(self, payload: dict, idempotency_key: str) -> str:
        response = await self._request(
            "POST",
            "/api/v1/simulations",
            json=payload,
            headers={"Idempotency-Key": idempotency_key},
        )
        try:
            return CoreJobCreated.model_validate(self._json(response)).job_id
        except ValidationError as exc:
            raise GeneratorError("generator returned an invalid job") from exc

    async def get_job(self, job_id: str) -> CoreJobInfo:
        response = await self._request("GET", f"/api/v1/jobs/{job_id}")
        try:
            return CoreJobInfo.model_validate(self._json(response))
        except ValidationError as exc:
            raise GeneratorError("generator returned invalid job metadata") from exc

    async def get_result(self, job_id: str) -> dict:
        response = await self._request("GET", f"/api/v1/jobs/{job_id}/result")
        return self._json(response)

    async def download_text(self, job_id: str, filename: str) -> str:
        if filename not in {"model.py", "model.mdl", "model.xmile"}:
            raise GeneratorError("artifact is not allowed")
        response = await self._request("GET", f"/api/v1/jobs/{job_id}/files/{filename}")
        try:
            return response.content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise GeneratorError("generator returned a non-text artifact") from exc
