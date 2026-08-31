"""Symmetric encryption for GitHub tokens at rest.

A single Fernet key is used, taken from TOKEN_ENCRYPTION_KEY. If that is not
set, a key is derived deterministically from SECRET_KEY so the app still runs
in development -- but rotating SECRET_KEY then invalidates stored tokens, so
set TOKEN_ENCRYPTION_KEY explicitly in production.
"""
from __future__ import annotations

import base64
import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken
from flask import current_app

log = logging.getLogger(__name__)

_CACHE: dict[str, Fernet] = {}


def _derive_key(secret: str) -> bytes:
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def _fernet() -> Fernet:
    configured = (current_app.config.get("TOKEN_ENCRYPTION_KEY") or "").strip()
    if configured:
        key = configured.encode("utf-8")
        cache_key = configured
    else:
        secret = current_app.config.get("SECRET_KEY") or "dev-secret-change-me"
        key = _derive_key(secret)
        cache_key = f"derived:{secret}"
        log.warning(
            "TOKEN_ENCRYPTION_KEY is not set; deriving encryption key from "
            "SECRET_KEY. Set TOKEN_ENCRYPTION_KEY before production use."
        )

    if cache_key not in _CACHE:
        _CACHE[cache_key] = Fernet(key)
    return _CACHE[cache_key]


def encrypt(plaintext: str | None) -> str | None:
    if plaintext is None:
        return None
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt(ciphertext: str | None) -> str | None:
    if ciphertext is None:
        return None
    try:
        return _fernet().decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:  # pragma: no cover - depends on key rotation
        raise ValueError(
            "Stored token could not be decrypted. The encryption key changed."
        ) from exc
