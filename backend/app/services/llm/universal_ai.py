"""Universal AI client from main10.py adapted for the sdCloud backend.

Supports text chat (via litellm), image/audio/video generation and OpenRouter
native endpoints via httpx. Synchronous by design; the async wrapper in
openrouter.py runs blocking calls in a thread pool.
"""

import base64
import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union

import httpx
import litellm
from litellm import completion
from openai import OpenAI


@dataclass
class AIResponse:
    """Response from the LLM."""

    text: Optional[str] = None
    images: List[str] = field(default_factory=list)
    audio: Optional[bytes] = None
    video_url: Optional[str] = None
    cost: Optional[float] = None
    model: Optional[str] = None


class UniversalAI:
    """Sync client for OpenRouter / LiteLLM."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        proxy: Optional[str] = None,
        default_text_model: str = "openrouter/google/gemma-4-31b-it:free",
    ):
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY") or os.getenv("AI_API_KEY")
        self.default_text_model = default_text_model

        # Allow proxy to be configured via PROXY_URL env var. In Docker the
        # original default socks5h://127.0.0.1:3066 will not exist, so default
        # to no proxy.
        self.proxy = proxy or os.getenv("PROXY_URL")

        self.http_client = httpx.Client(proxy=self.proxy) if self.proxy else httpx.Client()

        if self.proxy:
            litellm.client_session = httpx.Client(proxy=self.proxy)
            litellm.aclient_session = httpx.AsyncClient(proxy=self.proxy)

        if self.api_key:
            os.environ["OPENROUTER_API_KEY"] = self.api_key
            os.environ["OPENAI_API_KEY"] = self.api_key

        self.client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=self.api_key or "",
            http_client=self.http_client,
        )

    def _or_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://sdcloud.app",
            "X-Title": "sdCloud",
        }

    def chat(
        self,
        prompt: str,
        model: Optional[str] = None,
        system: Optional[str] = None,
        stream: bool = False,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> Union[AIResponse, Any]:
        """Send a chat completion request via litellm/OpenRouter."""
        messages: List[Dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload: Dict[str, Any] = {
            "model": model or self.default_text_model,
            "messages": messages,
            "stream": stream,
            "temperature": temperature,
            **kwargs,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        response = completion(**payload)

        if stream:
            return response

        return AIResponse(
            text=response.choices[0].message.content,
            cost=response._hidden_params.get("response_cost"),
            model=response.model,
        )

    def generate_image(
        self,
        prompt: str,
        model: str = "google/gemini-2.5-flash-image",
        aspect_ratio: str = "16:9",
        image_size: str = "2K",
        **kwargs: Any,
    ) -> AIResponse:
        """Generate an image via OpenRouter."""
        if model.startswith("openrouter/"):
            model = model[11:]

        raw_response = self.client.with_raw_response.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            extra_body={
                "modalities": ["image", "text"],
                "image_config": {
                    "aspect_ratio": aspect_ratio,
                    "image_size": image_size,
                    **kwargs.get("image_config", {}),
                },
            },
        )

        data = json.loads(raw_response.text)
        message = data["choices"][0]["message"]

        text = message.get("content") or ""
        images: List[str] = []

        if "images" in message:
            for img in message["images"]:
                url = img.get("image_url", {}).get("url")
                if url:
                    images.append(url)

        if not images and text:
            md = re.search(r"!\[.*?\]\((data:image/[^;]+;base64,[^)]+)\)", text)
            if md:
                images.append(md.group(1))
                text = re.sub(r"!\[.*?\]\((data:image/[^;]+;base64,[^)]+)\)", "", text).strip()
            else:
                dataurl = re.search(r"(data:image/[^;]+;base64,[A-Za-z0-9+/=]+)", text)
                if dataurl:
                    images.append(dataurl.group(1))
                    text = text.replace(dataurl.group(1), "").strip()

        return AIResponse(text=text, images=images, model=model)

    def speak(
        self,
        text: str,
        model: str = "hexgrad/kokoro-82m",
        voice: str = "af_alloy",
        response_format: str = "mp3",
        **kwargs: Any,
    ) -> AIResponse:
        """Text-to-speech via OpenRouter audio API."""
        resp = self.http_client.post(
            "https://openrouter.ai/api/v1/audio/speech",
            headers=self._or_headers(),
            json={
                "model": model,
                "input": text,
                "voice": voice,
                "response_format": response_format,
                **kwargs,
            },
            timeout=60,
        )
        resp.raise_for_status()
        return AIResponse(audio=resp.content, model=model)

    def generate_music(
        self,
        prompt: str,
        model: str = "google/lyria-3-clip-preview",
        **kwargs: Any,
    ) -> AIResponse:
        """Generate music via OpenRouter streaming audio API."""
        if model.startswith("openrouter/"):
            model = model[11:]

        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "modalities": ["text", "audio"],
            "stream": True,
            **kwargs,
        }

        with self.http_client.stream(
            "POST",
            "https://openrouter.ai/api/v1/chat/completions",
            headers=self._or_headers(),
            json=payload,
            timeout=120,
        ) as response:
            response.raise_for_status()

            audio_chunks: List[str] = []
            transcript_chunks: List[str] = []

            for line in response.iter_lines():
                if not line:
                    continue
                decoded = line.decode("utf-8")
                if not decoded.startswith("data: "):
                    continue
                data = decoded[len("data: ") :]
                if data.strip() == "[DONE]":
                    break

                try:
                    chunk = json.loads(data)
                    delta = chunk["choices"][0].get("delta", {})
                    audio = delta.get("audio", {})
                    if audio.get("data"):
                        audio_chunks.append(audio["data"])
                    if audio.get("transcript"):
                        transcript_chunks.append(audio["transcript"])
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue

        full_audio = b""
        if audio_chunks:
            full_audio_b64 = "".join(audio_chunks)
            full_audio = base64.b64decode(full_audio_b64)

        transcript = "".join(transcript_chunks)

        return AIResponse(
            text=transcript if transcript else None,
            audio=full_audio if full_audio else None,
            model=model,
        )

    def transcribe(
        self,
        audio_path: str,
        model: str = "openai/whisper-1",
        language: Optional[str] = None,
        **kwargs: Any,
    ) -> AIResponse:
        """Speech-to-text via OpenRouter audio API."""
        with open(audio_path, "rb") as f:
            audio_b64 = base64.b64encode(f.read()).decode()

        ext = os.path.splitext(audio_path)[1].lower().replace(".", "")
        fmt_map = {
            "mp3": "mp3",
            "wav": "wav",
            "m4a": "m4a",
            "ogg": "ogg",
            "flac": "flac",
            "webm": "webm",
            "aac": "aac",
        }
        audio_format = fmt_map.get(ext, "mp3")

        payload: Dict[str, Any] = {
            "model": model,
            "input_audio": {
                "data": audio_b64,
                "format": audio_format,
            },
            **kwargs,
        }
        if language:
            payload["language"] = language

        resp = self.http_client.post(
            "https://openrouter.ai/api/v1/audio/transcriptions",
            headers=self._or_headers(),
            json=payload,
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()
        return AIResponse(text=data.get("text"), model=model)

    def generate_video(
        self,
        prompt: str,
        model: str = "openrouter/luma-ai/seedance-2.0",
        duration: int = 5,
        resolution: str = "720p",
        poll_interval: int = 5,
        max_wait: int = 300,
        **kwargs: Any,
    ) -> AIResponse:
        """Generate video via OpenRouter async video API."""
        r = self.http_client.post(
            "https://openrouter.ai/api/v1/videos",
            headers=self._or_headers(),
            json={
                "model": model,
                "prompt": prompt,
                "duration": duration,
                "resolution": resolution,
                **kwargs,
            },
        )
        r.raise_for_status()
        job = r.json()
        job_id = job["id"]

        start = time.time()
        while time.time() - start < max_wait:
            status = self.http_client.get(
                f"https://openrouter.ai/api/v1/videos/{job_id}",
                headers=self._or_headers(),
            ).json()

            if status.get("status") == "completed":
                return AIResponse(video_url=status.get("url"), model=model)
            elif status.get("status") == "failed":
                raise RuntimeError(f"Video generation failed: {status.get('error')}")

            time.sleep(poll_interval)

        raise TimeoutError("Video generation timed out")

    @staticmethod
    def save_base64(data: str, path: str) -> None:
        if data.startswith("data:image"):
            data = data.split(",")[1]
        with open(path, "wb") as f:
            f.write(base64.b64decode(data))
        print(f"✅ Saved image: {path}")

    @staticmethod
    def save_bytes(data: bytes, path: str) -> None:
        with open(path, "wb") as f:
            f.write(data)
        print(f"✅ Saved file: {path}")
