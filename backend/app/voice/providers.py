"""Speech providers behind two small interfaces, so the engine is a config choice:

STT_PROVIDER=local       → faster-whisper on this machine (free, private, no quotas)
STT_PROVIDER=elevenlabs  → ElevenLabs Scribe API
TTS_PROVIDER=local       → Kokoro (ONNX) on this machine
TTS_PROVIDER=elevenlabs  → ElevenLabs text-to-speech API (best quality)
"""

import asyncio
import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Protocol

import httpx

from app.config import get_settings
from app.voice.audio import decode_to_mono_16k, to_wav

logger = logging.getLogger(__name__)

ELEVENLABS_API = "https://api.elevenlabs.io/v1"


@dataclass
class Speech:
    audio: bytes
    mime: str  # e.g. "audio/wav", "audio/mpeg" — the browser decodes either


class STT(Protocol):
    name: str

    async def transcribe(self, audio: bytes) -> str: ...

    async def warmup(self) -> None: ...


class TTS(Protocol):
    name: str

    async def synthesize(self, text: str) -> Speech: ...

    async def warmup(self) -> None: ...


# ---------- Local (open-source) ----------


class WhisperSTT:
    name = "faster-whisper"

    def __init__(self, model: str):
        self._model_name = model
        self._model = None
        self._lock = asyncio.Lock()

    def _load(self) -> None:
        if self._model is None:
            from faster_whisper import WhisperModel  # heavy import, load once

            # int8 on CPU: ~4x smaller and faster than float32 with minimal accuracy loss.
            self._model = WhisperModel(self._model_name, device="cpu", compute_type="int8")

    async def warmup(self) -> None:
        await asyncio.to_thread(self._load)

    def _run(self, audio: bytes) -> str:
        self._load()
        samples = decode_to_mono_16k(audio)
        if samples.size == 0:
            return ""
        # vad_filter skips silence; beam_size=1 (greedy) trades a little accuracy for speed.
        segments, _ = self._model.transcribe(samples, language="en", beam_size=1, vad_filter=True)
        return " ".join(s.text.strip() for s in segments).strip()

    async def transcribe(self, audio: bytes) -> str:
        # CPU-bound: run in a thread so the event loop keeps serving other requests.
        # The lock keeps one transcription at a time on a laptop CPU.
        async with self._lock:
            return await asyncio.to_thread(self._run, audio)


class KokoroTTS:
    name = "kokoro"

    def __init__(self, models_dir: str, voice: str):
        self._dir = Path(models_dir)
        self._voice = voice
        self._kokoro = None

    def _load(self) -> None:
        if self._kokoro is None:
            from kokoro_onnx import Kokoro

            model, voices = self._dir / "kokoro-v1.0.int8.onnx", self._dir / "voices-v1.0.bin"
            if not model.exists():
                raise RuntimeError(
                    "Kokoro model missing — run: uv run python -m scripts.download_voice_models"
                )
            self._kokoro = Kokoro(str(model), str(voices))

    async def warmup(self) -> None:
        await asyncio.to_thread(self._load)
        await self.synthesize("Hello.")  # first inference is slower; pay it at startup

    def _run(self, text: str) -> Speech:
        self._load()
        samples, rate = self._kokoro.create(text, voice=self._voice, lang="en-us")
        return Speech(to_wav(samples, rate), "audio/wav")

    async def synthesize(self, text: str) -> Speech:
        return await asyncio.to_thread(self._run, text)


# ---------- ElevenLabs ----------


class ElevenLabsSTT:
    name = "elevenlabs-scribe"

    def __init__(self, api_key: str, model: str, http: httpx.AsyncClient | None = None):
        self._model = model
        self._http = http or httpx.AsyncClient(base_url=ELEVENLABS_API, timeout=30)
        self._headers = {"xi-api-key": api_key}

    async def warmup(self) -> None:
        pass  # nothing to load: the model runs on ElevenLabs' servers

    async def transcribe(self, audio: bytes) -> str:
        response = await self._http.post(
            "/speech-to-text",
            headers=self._headers,
            data={"model_id": self._model, "language_code": "en"},
            files={"file": ("speech.webm", audio, "application/octet-stream")},
        )
        response.raise_for_status()
        return response.json().get("text", "").strip()


class ElevenLabsTTS:
    name = "elevenlabs"

    def __init__(
        self, api_key: str, voice_id: str, model: str, http: httpx.AsyncClient | None = None
    ):
        self._voice = voice_id
        self._model = model
        self._http = http or httpx.AsyncClient(base_url=ELEVENLABS_API, timeout=30)
        self._headers = {"xi-api-key": api_key}

    async def warmup(self) -> None:
        pass

    async def synthesize(self, text: str) -> Speech:
        response = await self._http.post(
            f"/text-to-speech/{self._voice}",
            headers=self._headers,
            params={"output_format": "mp3_44100_128"},
            json={"text": text, "model_id": self._model},
        )
        response.raise_for_status()
        return Speech(response.content, "audio/mpeg")


# ---------- Factory ----------


def _require_key() -> str:
    key = get_settings().elevenlabs_api_key
    if not key:
        raise RuntimeError("ElevenLabs selected but ELEVENLABS_API_KEY is not set")
    return key


@lru_cache
def get_stt() -> STT:
    s = get_settings()
    if s.stt_provider == "elevenlabs":
        return ElevenLabsSTT(_require_key(), s.elevenlabs_stt_model)
    return WhisperSTT(s.whisper_model)


@lru_cache
def get_tts() -> TTS:
    s = get_settings()
    if s.tts_provider == "elevenlabs":
        return ElevenLabsTTS(_require_key(), s.elevenlabs_voice_id, s.elevenlabs_tts_model)
    return KokoroTTS(s.voice_models_dir, s.kokoro_voice)


async def warm_up_voice() -> None:
    """Load speech models in the background at API startup, so the first caller doesn't
    wait for multi-second model loading. Failures are logged, never fatal."""
    for provider in (get_stt(), get_tts()):
        try:
            await provider.warmup()
            logger.info("Voice provider ready: %s", provider.name)
        except Exception:
            logger.warning("Could not warm up %s", provider.name, exc_info=True)
