"""Voice: speech-to-text and text-to-speech for talking with NOVA (relayed to the private voice service).

Audio is never stored: the browser's recording is forwarded to the voice service and discarded; only the transcript
comes back and is then sent like typed text (audit, redaction and prompt-injection defenses apply unchanged).
"""

from __future__ import annotations

from typing import Literal

import httpx
from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from nova.config import get_settings
from nova_api.auth import CurrentPrincipal
from nova_api.errors import ApiError

router = APIRouter(prefix="/voice", tags=["voice"])
MAX_AUDIO_BYTES = 10 * 1024 * 1024
TRANSPORT: httpx.AsyncBaseTransport | None = None  # tests inject the fake voice service here


def _unavailable() -> ApiError:
    return ApiError(503, "voice_unavailable", "Voice is not available right now. You can keep typing to NOVA.")


async def _post(path: str, **kwargs: object) -> httpx.Response:
    settings = get_settings()
    if not settings.voice_url:
        raise _unavailable()
    try:
        async with httpx.AsyncClient(
            base_url=settings.voice_url.rstrip("/"), timeout=settings.voice_timeout_seconds, transport=TRANSPORT
        ) as client:
            response = await client.post(path, headers={"X-Voice-Token": settings.voice_token}, **kwargs)  # type: ignore[arg-type]
    except httpx.HTTPError as exc:
        raise _unavailable() from exc
    if response.status_code == 413:
        raise ApiError(413, "audio_too_long", "That recording is too long — keep it under a minute and a half.")
    if response.status_code >= 400:
        raise _unavailable()
    return response


@router.get("/status")
async def status(principal: CurrentPrincipal) -> dict[str, bool]:
    return {"enabled": bool(get_settings().voice_url)}


@router.post("/transcribe")
async def transcribe(
    principal: CurrentPrincipal,
    audio: UploadFile = File(...),
    language: Literal["fr", "en"] | None = Form(default=None),
) -> dict[str, object]:
    data = await audio.read()
    if not data:
        raise ApiError(422, "empty_audio", "NOVA didn't hear anything.")
    if len(data) > MAX_AUDIO_BYTES:
        raise ApiError(413, "audio_too_long", "That recording is too long — keep it under a minute and a half.")
    response = await _post(
        "/transcribe",
        files={"audio": (audio.filename or "speech.webm", data, audio.content_type or "audio/webm")},
        data={"language": language} if language else {},
    )
    return response.json()


class SpeakIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    language: Literal["fr", "en"] = "fr"


@router.post("/speak")
async def speak(body: SpeakIn, principal: CurrentPrincipal) -> Response:
    response = await _post("/speak", json=body.model_dump())
    return Response(response.content, media_type="audio/wav", headers={"Cache-Control": "no-store"})
