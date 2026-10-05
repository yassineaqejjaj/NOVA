"""Fake voice service for tests and E2E: fixed transcript, tiny WAV (no models)."""

from __future__ import annotations

import io
import os
import wave

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

TOKEN = os.environ.get("VOICE_TOKEN", "test-voice-token-0123456789abcdef")
TRANSCRIPT = os.environ.get("FAKE_VOICE_TRANSCRIPT", "What is a good north star metric for an evaluation platform?")
app = FastAPI()
calls: list[str] = []


def _auth(token: str) -> None:
    if token != TOKEN:
        raise HTTPException(status_code=401)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/transcribe")
async def transcribe(
    audio: UploadFile = File(...), language: str | None = Form(default=None), x_voice_token: str = Header(default="")
):
    _auth(x_voice_token)
    size = len(await audio.read())
    calls.append(f"transcribe:{size}")
    return {"text": TRANSCRIPT, "language": language or "en", "duration": 2.0, "latency_ms": 5}


class SpeakIn(BaseModel):
    text: str
    language: str = "fr"


@app.post("/speak")
def speak(body: SpeakIn, x_voice_token: str = Header(default="")) -> Response:
    _auth(x_voice_token)
    calls.append(f"speak:{body.language}:{body.text[:40]}")
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:  # 0.3 s of silence
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\x00\x00" * 4800)
    return Response(buffer.getvalue(), media_type="audio/wav")
