"""NOVA voice service (private network only; NOVA's API is the only client).

* ``POST /transcribe`` — multipart ``audio`` (webm/opus, mp4/aac, wav…; decoded by PyAV), optional ``language``
  (``fr``/``en``; detected when absent) → ``{text, language, duration}``.
* ``POST /speak`` — ``{text, language}`` → ``audio/wav`` (Piper voice per language).

No audio or text is stored or logged. Requests must carry ``X-Voice-Token`` (shared secret with NOVA's API).
"""

from __future__ import annotations

import asyncio
import hmac
import io
import os
import tempfile
import time
import wave
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

TOKEN = os.environ.get("VOICE_TOKEN", "")
MODELS = Path(os.environ.get("VOICE_MODELS_DIR", "/models"))
WHISPER_MODEL = os.environ.get("VOICE_WHISPER_MODEL", "small")
WHISPER_THREADS = int(os.environ.get("VOICE_WHISPER_THREADS", "0"))  # 0 = all cores
VOICES = {"fr": os.environ.get("VOICE_FR", "fr_FR-siwis-medium"), "en": os.environ.get("VOICE_EN", "en_US-amy-medium")}
MAX_AUDIO_BYTES = 10 * 1024 * 1024
MAX_SECONDS = 90


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # Load models before the first request (a cold first call would take several seconds).
    await asyncio.to_thread(whisper)
    for language in VOICES:
        await asyncio.to_thread(piper, language)
    yield


app = FastAPI(title="NOVA voice", docs_url=None, redoc_url=None, lifespan=lifespan)
_lock = asyncio.Semaphore(int(os.environ.get("VOICE_CONCURRENCY", "2")))


def require_token(x_voice_token: str = Header(default="")) -> None:
    if not TOKEN or not hmac.compare_digest(x_voice_token.encode(), TOKEN.encode()):
        raise HTTPException(status_code=401, detail="unauthorized")


@lru_cache
def whisper():  # type: ignore[no-untyped-def]
    from faster_whisper import WhisperModel

    local = MODELS / f"faster-whisper-{WHISPER_MODEL}"
    return WhisperModel(
        str(local) if local.exists() else WHISPER_MODEL, device="cpu", compute_type="int8", cpu_threads=WHISPER_THREADS
    )


@lru_cache(maxsize=4)
def piper(language: str):  # type: ignore[no-untyped-def]
    from piper import PiperVoice

    name = VOICES[language]
    return PiperVoice.load(MODELS / f"{name}.onnx", config_path=MODELS / f"{name}.onnx.json")


@app.get("/health")
def health() -> dict[str, object]:
    return {"status": "ok", "whisper": WHISPER_MODEL, "voices": VOICES}


def _transcribe(path: str, language: str | None) -> dict[str, object]:
    segments, info = whisper().transcribe(
        path, language=language, beam_size=1, vad_filter=True, vad_parameters={"min_silence_duration_ms": 400}
    )
    if info.duration > MAX_SECONDS:
        raise HTTPException(status_code=413, detail="audio too long")
    text = " ".join(s.text.strip() for s in segments).strip()
    return {"text": text, "language": info.language, "duration": round(info.duration, 2)}


@app.post("/transcribe", dependencies=[Depends(require_token)])
async def transcribe(
    audio: UploadFile = File(...), language: Literal["fr", "en"] | None = Form(default=None)
) -> dict[str, object]:
    data = await audio.read()
    if not data:
        raise HTTPException(status_code=422, detail="empty audio")
    if len(data) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="audio too large")
    suffix = Path(audio.filename or "audio.webm").suffix or ".webm"
    with tempfile.NamedTemporaryFile(suffix=suffix) as tmp:  # deleted on close: nothing is kept
        tmp.write(data)
        tmp.flush()
        async with _lock:
            started = time.perf_counter()
            result = await asyncio.to_thread(_transcribe, tmp.name, language)
            result["latency_ms"] = round((time.perf_counter() - started) * 1000)
            return result


class SpeakIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    language: Literal["fr", "en"] = "fr"


def _speak(text: str, language: str) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        piper(language).synthesize_wav(text, wav)
    return buffer.getvalue()


@app.post("/speak", dependencies=[Depends(require_token)])
async def speak(body: SpeakIn) -> Response:
    async with _lock:
        audio = await asyncio.to_thread(_speak, body.text, body.language)
    return Response(audio, media_type="audio/wav", headers={"Cache-Control": "no-store"})
