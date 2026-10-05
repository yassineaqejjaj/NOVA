# NOVA voice service (faster-whisper STT + Piper TTS), CPU only. Models are baked in at build time.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 VOICE_MODELS_DIR=/models HF_HUB_DISABLE_TELEMETRY=1
WORKDIR /app
COPY services/voice/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --create-home --uid 10001 nova && install -d -o nova /models
COPY services/voice/download_models.py ./
USER nova
RUN python download_models.py && rm -rf /home/nova/.cache
COPY services/voice/nova_voice ./nova_voice
ENV HF_HUB_OFFLINE=1
EXPOSE 8300
# VOICE_HOST=:: on platforms with IPv6 private networking (Railway); 0.0.0.0 elsewhere.
CMD ["sh", "-c", "exec uvicorn nova_voice.app:app --host ${VOICE_HOST:-0.0.0.0} --port ${PORT:-8300} --workers 1"]
