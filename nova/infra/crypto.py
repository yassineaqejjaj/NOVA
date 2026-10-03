"""Symmetric encryption of stored integration secrets (Fernet, key from NOVA_SECRETS_KEY)."""

from __future__ import annotations

import base64
import hashlib
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from nova.config import get_settings


@lru_cache
def _fernet() -> Fernet:
    key = base64.urlsafe_b64encode(hashlib.sha256(get_settings().secrets_key.encode()).digest())
    return Fernet(key)


def encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str | None:
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken:
        return None
