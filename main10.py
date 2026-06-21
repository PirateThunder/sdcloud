import os
import base64
import json
import re
import time
import httpx
from dataclasses import dataclass, field
from typing import Optional, List, Union, Dict, Any
from dotenv import load_dotenv

import litellm
from litellm import completion
from openai import OpenAI

load_dotenv()

@dataclass
class AIResponse:
    text: Optional[str] = None
    images: List[str] = field(default_factory=list)
    audio: Optional[bytes] = None
    video_url: Optional[str] = None
    cost: Optional[float] = None
    model: Optional[str] = None


class UniversalAI:
    def __init__(
        self,
        api_key: Optional[str] = None,
        proxy: Optional[str] = "socks5h://127.0.0.1:3066",
        default_text_model: str = "openrouter/google/gemma-4-31b-it:free",
    ):
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY") or os.getenv("AI_API_KEY")
        self.default_text_model = default_text_model
        
        self.http_client = httpx.Client(proxy=proxy) if proxy else httpx.Client()
        
        if proxy:
            litellm.client_session = httpx.Client(proxy=proxy)
            litellm.aclient_session = httpx.AsyncClient(proxy=proxy)
        
        os.environ["OPENROUTER_API_KEY"] = self.api_key
        os.environ["OPENAI_API_KEY"] = self.api_key

        self.client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=self.api_key,
            http_client=self.http_client
        )

    def _or_headers(self):
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://localhost",
            "X-Title": "UniversalAI"
        }

    def chat(
        self,
        prompt: str,
        model: Optional[str] = None,
        system: Optional[str] = None,
        stream: bool = False,
        **kwargs
    ) -> Union[AIResponse, Any]:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        
        response = completion(
            model=model or self.default_text_model,
            messages=messages,
            stream=stream,
            **kwargs
        )
        
        if stream:
            return response
        
        return AIResponse(
            text=response.choices[0].message.content,
            cost=response._hidden_params.get("response_cost"),
            model=response.model
        )

    def generate_image(
        self,
        prompt: str,
        model: str = "google/gemini-2.5-flash-image",
        aspect_ratio: str = "16:9",
        image_size: str = "2K",
        **kwargs
    ) -> AIResponse:
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
                    **kwargs.get("image_config", {})
                }
            }
        )
        
        data = json.loads(raw_response.text)
        message = data["choices"][0]["message"]
        
        text = message.get("content") or ""
        images = []
        
        if "images" in message:
            for img in message["images"]:
                url = img.get("image_url", {}).get("url")
                if url:
                    images.append(url)
        
        if not images and text:
            md = re.search(r'!\[.*?\]\((data:image/[^;]+;base64,[^)]+)\)', text)
            if md:
                images.append(md.group(1))
                text = re.sub(r'!\[.*?\]\(data:image/[^;]+;base64,[^)]+\)', '', text).strip()
            else:
                dataurl = re.search(r'(data:image/[^;]+;base64,[A-Za-z0-9+/=]+)', text)
                if dataurl:
                    images.append(dataurl.group(1))
                    text = text.replace(dataurl.group(1), '').strip()
        
        return AIResponse(text=text, images=images, model=model)

    # ═══════════════════════════════════════════════════════
    # AUDIO — TTS (прямой HTTP, OpenAI SDK не работает с OpenRouter TTS)
    # ═══════════════════════════════════════════════════════
    def speak(
        self,
        text: str,
        model: str = "hexgrad/kokoro-82m",
        voice: str = "af_alloy",
        response_format: str = "mp3",
        **kwargs
    ) -> AIResponse:
        """
        Генерация речи через OpenRouter TTS API (прямой HTTP).
        Модели: hexgrad/kokoro-82m (бесплатная!), openai/gpt-4o-mini-tts-2025-12-15
        Голоса зависят от модели — проверяй на странице модели.
        """
        resp = self.http_client.post(
            "https://openrouter.ai/api/v1/audio/speech",
            headers=self._or_headers(),
            json={
                "model": model,
                "input": text,
                "voice": voice,
                "response_format": response_format,
                **kwargs
            },
            timeout=60
        )
        resp.raise_for_status()
        return AIResponse(audio=resp.content, model=model)

    # ═══════════════════════════════════════════════════════
    # AUDIO — Music Generation (Lyria 3 через SSE streaming)
    # ═══════════════════════════════════════════════════════
    def generate_music(
        self,
        prompt: str,
        model: str = "google/lyria-3-clip-preview",
        **kwargs
    ) -> AIResponse:
        """
        Генерация музыки через Google Lyria 3 (OpenRouter).
        Требует streaming — аудио приходит в чанках SSE.
        Модели: google/lyria-3-clip-preview (30сек, $0.04), google/lyria-3-pro-preview (полная, $0.08)
        """
        if model.startswith("openrouter/"):
            model = model[11:]
        
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "modalities": ["text", "audio"],
            "stream": True,
            **kwargs
        }
        
        with self.http_client.stream(
            "POST",
            "https://openrouter.ai/api/v1/chat/completions",
            headers=self._or_headers(),
            json=payload,
            timeout=120
        ) as response:
            response.raise_for_status()
            
            audio_chunks = []
            transcript_chunks = []
            
            for line in response.iter_lines():
                if not line:
                    continue
                decoded = line.decode("utf-8")
                if not decoded.startswith("data: "):
                    continue
                data = decoded[len("data: "):]
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
            model=model
        )

    # ═══════════════════════════════════════════════════════
    # AUDIO — STT (Speech-to-Text)
    # ═══════════════════════════════════════════════════════
    def transcribe(
        self,
        audio_path: str,
        model: str = "openai/whisper-1",
        language: Optional[str] = None,
        **kwargs
    ) -> AIResponse:
        """
        Распознавание речи через OpenRouter STT API.
        Модели: openai/whisper-1, openai/whisper-large-v3, google/chirp-3
        """
        with open(audio_path, "rb") as f:
            audio_b64 = base64.b64encode(f.read()).decode()
        
        ext = os.path.splitext(audio_path)[1].lower().replace('.', '')
        fmt_map = {"mp3": "mp3", "wav": "wav", "m4a": "m4a", "ogg": "ogg",
                   "flac": "flac", "webm": "webm", "aac": "aac"}
        audio_format = fmt_map.get(ext, "mp3")
        
        payload = {
            "model": model,
            "input_audio": {
                "data": audio_b64,
                "format": audio_format
            },
            **kwargs
        }
        if language:
            payload["language"] = language
        
        resp = self.http_client.post(
            "https://openrouter.ai/api/v1/audio/transcriptions",
            headers=self._or_headers(),
            json=payload,
            timeout=120
        )
        resp.raise_for_status()
        data = resp.json()
        return AIResponse(text=data.get("text"), model=model)

    # ═══════════════════════════════════════════════════════
    # VIDEO — OpenRouter async API
    # ═══════════════════════════════════════════════════════
    def generate_video(
        self,
        prompt: str,
        model: str = "openrouter/luma-ai/seedance-2.0",
        duration: int = 5,
        resolution: str = "720p",
        poll_interval: int = 5,
        max_wait: int = 300,
        **kwargs
    ) -> AIResponse:
        r = self.http_client.post(
            "https://openrouter.ai/api/v1/videos",
            headers=self._or_headers(),
            json={
                "model": model,
                "prompt": prompt,
                "duration": duration,
                "resolution": resolution,
                **kwargs
            }
        )
        r.raise_for_status()
        job = r.json()
        job_id = job["id"]
        
        start = time.time()
        while time.time() - start < max_wait:
            status = self.http_client.get(
                f"https://openrouter.ai/api/v1/videos/{job_id}",
                headers=self._or_headers()
            ).json()
            
            if status.get("status") == "completed":
                return AIResponse(video_url=status.get("url"), model=model)
            elif status.get("status") == "failed":
                raise RuntimeError(f"Video generation failed: {status.get('error')}")
            
            time.sleep(poll_interval)
        
        raise TimeoutError("Video generation timed out")

    @staticmethod
    def save_base64(data: str, path: str):
        if data.startswith("data:image"):
            data = data.split(",")[1]
        with open(path, "wb") as f:
            f.write(base64.b64decode(data))
        print(f"✅ Saved image: {path}")

    @staticmethod
    def save_bytes(data: bytes, path: str):
        with open(path, "wb") as f:
            f.write(data)
        print(f"✅ Saved file: {path}")


if __name__ == "__main__":
    ai = UniversalAI(proxy="socks5h://127.0.0.1:3066")
    
    # 1. Текст
    # r = ai.chat("Объясни квантовую запутанность простыми словами")
    # print(f"\n📝 TEXT:\n{r.text}")
    
    # 2. Изображение
    # img = ai.generate_image(
    #     "Киберпанк город ночью, неоновые огни, дождь",
    #     model="openrouter/google/gemini-2.5-flash-image",
    #     aspect_ratio="16:9",
    #     image_size="2K"
    # )
    # if img.images:
    #     ai.save_base64(img.images[0], "cyberpunk.png")
    #     print("Фото сохранено!")
    # if img.text:
    #     print(f"\n🖼️  Image description: {img.text}")
    
    # 3. Аудио TTS (речь) — бесплатная модель!
    try:
        audio = ai.speak("Привет, это тестовое сообщение от искусственного интеллекта")
        ai.save_bytes(audio.audio, "voice.mp3")
        print("TTS аудио сохранено!")
    except Exception as e:
        print(f"❌ TTS ошибка: {e}")
    
    # 4. Музыка (Lyria 3)
    try:
        music = ai.generate_music("An upbeat electronic track with synth leads, 120 BPM")
        if music.audio:
            ai.save_bytes(music.audio, "music.mp3")
            print("Музыка сохранена!")
        if music.text:
            print(f"\n🎵 Lyrics: {music.text}")
    except Exception as e:
        print(f"❌ Music ошибка: {e}")
    
    # 5. STT (если есть файл)
    # text = ai.transcribe("voice.mp3")
    # print(f"\n🎤 Transcribed: {text.text}")
    
    # 6. Видео
    # vid = ai.generate_video(
    #     "A cat playing piano in a jazz bar",
    #     duration=5,
    #     resolution="720p"
    # )
    # print(f"\n🎬 Video URL: {vid.video_url}")