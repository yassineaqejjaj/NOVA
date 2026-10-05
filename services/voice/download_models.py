"""Download the voice models into VOICE_MODELS_DIR (build time, so the service starts offline)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from huggingface_hub import snapshot_download

MODELS = Path(os.environ.get("VOICE_MODELS_DIR", "/models"))
WHISPER = os.environ.get("VOICE_WHISPER_MODEL", "small")
VOICES = [os.environ.get("VOICE_FR", "fr_FR-siwis-medium"), os.environ.get("VOICE_EN", "en_US-amy-medium")]

MODELS.mkdir(parents=True, exist_ok=True)
snapshot_download(f"Systran/faster-whisper-{WHISPER}", local_dir=MODELS / f"faster-whisper-{WHISPER}")
for voice in VOICES:
    subprocess.run([sys.executable, "-m", "piper.download_voices", "--download-dir", str(MODELS), voice], check=True)
print("models ready:", sorted(p.name for p in MODELS.iterdir()))
