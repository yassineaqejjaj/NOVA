"""Voice: speech-to-text and text-to-speech for talking with NOVA.

Providers (per direction): ElevenLabs (cloud, `NOVA_VOICE_*_PROVIDER=elevenlabs`) or NOVA's self-hosted voice service
(faster-whisper + Piper, private network). When the primary provider fails, the self-hosted service is used if it is
deployed. Audio is never stored: it is forwarded, transcribed and discarded; the transcript is then sent like typed text
(audit, redaction and prompt-injection defenses apply unchanged).
"""

from __future__ import annotations

import logging
from typing import Literal

import httpx
from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from nova.config import Settings, get_settings
from nova_api.auth import CurrentPrincipal
from nova_api.errors import ApiError

router = APIRouter(prefix="/voice", tags=["voice"])
log = logging.getLogger(__name__)
MAX_AUDIO_BYTES = 10 * 1024 * 1024
ELEVENLABS = "https://api.elevenlabs.io/v1"
TRANSPORT: httpx.AsyncBaseTransport | None = None  # tests inject fake services here


class VoiceUnavailable(Exception):
    pass


def _unavailable() -> ApiError:
    return ApiError(503, "voice_unavailable", "Voice is not available right now. You can keep typing to NOVA.")


def _too_long() -> ApiError:
    return ApiError(413, "audio_too_long", "That recording is too long — keep it under a minute and a half.")


def _client(settings: Settings, base_url: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=base_url, timeout=settings.voice_timeout_seconds, transport=TRANSPORT)


# --- Self-hosted voice service ---------------------------------------------------------------------


async def _selfhosted(settings: Settings, path: str, **kwargs: object) -> httpx.Response:
    if not settings.voice_url:
        raise VoiceUnavailable("self-hosted voice service not configured")
    try:
        async with _client(settings, settings.voice_url.rstrip("/")) as client:
            response = await client.post(path, headers={"X-Voice-Token": settings.voice_token}, **kwargs)  # type: ignore[arg-type]
    except httpx.HTTPError as exc:
        raise VoiceUnavailable(str(exc)) from exc
    if response.status_code == 413:
        raise _too_long()
    if response.status_code >= 400:
        raise VoiceUnavailable(f"voice service {response.status_code}")
    return response


# --- ElevenLabs ------------------------------------------------------------------------------------


async def _elevenlabs(settings: Settings, path: str, **kwargs: object) -> httpx.Response:
    if not settings.elevenlabs_api_key:
        raise VoiceUnavailable("ElevenLabs not configured")
    try:
        async with _client(settings, ELEVENLABS) as client:
            response = await client.post(path, headers={"xi-api-key": settings.elevenlabs_api_key}, **kwargs)  # type: ignore[arg-type]
    except httpx.HTTPError as exc:
        raise VoiceUnavailable(str(exc)) from exc
    if response.status_code >= 400:
        raise VoiceUnavailable(f"ElevenLabs {response.status_code}: {response.text[:160]}")
    return response


def _language(code: str | None) -> str:
    """ElevenLabs returns ISO 639-3 codes ("fra", "eng"); NOVA uses "fr" / "en"."""
    code = (code or "").lower()
    return {"fra": "fr", "fre": "fr", "eng": "en"}.get(code, code[:2] or "en")


# --- Routes ----------------------------------------------------------------------------------------


@router.get("/status")
async def status(principal: CurrentPrincipal) -> dict[str, object]:
    settings = get_settings()

    def available(provider: str) -> bool:
        return bool(settings.elevenlabs_api_key) if provider == "elevenlabs" else bool(settings.voice_url)

    stt = available(settings.voice_stt_provider) or bool(settings.voice_url)
    tts = available(settings.voice_tts_provider) or bool(settings.voice_url)
    return {"enabled": stt and tts, "stt": settings.voice_stt_provider, "tts": settings.voice_tts_provider}


@router.post("/transcribe")
async def transcribe(
    principal: CurrentPrincipal,
    audio: UploadFile = File(...),
    language: Literal["fr", "en"] | None = Form(default=None),
) -> dict[str, object]:
    settings = get_settings()
    data = await audio.read()
    if not data:
        raise ApiError(422, "empty_audio", "NOVA didn't hear anything.")
    if len(data) > MAX_AUDIO_BYTES:
        raise _too_long()
    upload = (audio.filename or "speech.webm", data, audio.content_type or "audio/webm")
    if settings.voice_stt_provider == "elevenlabs":
        try:
            fields = {"model_id": settings.elevenlabs_stt_model, **({"language_code": language} if language else {})}
            body = (await _elevenlabs(settings, "/speech-to-text", files={"file": upload}, data=fields)).json()
            return {
                "text": str(body.get("text") or "").strip(),
                "language": _language(body.get("language_code")),
                "provider": "elevenlabs",
            }
        except VoiceUnavailable as exc:
            log.warning("ElevenLabs transcription failed, falling back: %s", exc)
    try:
        body = (
            await _selfhosted(settings, "/transcribe", files={"audio": upload}, data={"language": language} if language else {})
        ).json()
    except VoiceUnavailable as exc:
        raise _unavailable() from exc
    return {**body, "provider": "selfhosted"}


class SpeakIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    language: Literal["fr", "en"] = "fr"


@router.post("/speak")
async def speak(body: SpeakIn, principal: CurrentPrincipal) -> Response:
    settings = get_settings()
    if settings.voice_tts_provider == "elevenlabs":
        try:
            response = await _elevenlabs(
                settings,
                f"/text-to-speech/{settings.elevenlabs_voice_id}?output_format=mp3_44100_128",
                json={"text": body.text, "model_id": settings.elevenlabs_tts_model, "language_code": body.language},
            )
            return Response(response.content, media_type="audio/mpeg", headers={"Cache-Control": "no-store"})
        except VoiceUnavailable as exc:
            log.warning("ElevenLabs speech failed, falling back: %s", exc)
    try:
        response = await _selfhosted(settings, "/speak", json=body.model_dump())
    except VoiceUnavailable as exc:
        raise _unavailable() from exc
    return Response(response.content, media_type="audio/wav", headers={"Cache-Control": "no-store"})
