"""Security and cryptographic utilities for secret references and token encryption."""

import base64
import hashlib
from cryptography.fernet import Fernet, InvalidToken
from backend.app.core.config import get_settings


def _derive_fernet_key(secret: str) -> bytes:
    """Derive a deterministic 32-byte url-safe base64-encoded key from SECRET_KEY."""
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def encrypt_secret(plaintext: str) -> str:
    """Encrypt a plaintext secret (e.g., API key or token) using Fernet."""
    if not plaintext:
        return ""
    settings = get_settings()
    key = _derive_fernet_key(settings.SECRET_KEY)
    fernet = Fernet(key)
    return fernet.encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_secret(ciphertext: str) -> str:
    """Decrypt a Fernet-encrypted ciphertext string."""
    if not ciphertext:
        return ""
    # If the secret is stored as an environment reference like env:HUNTER_API_KEY
    if ciphertext.startswith("env:"):
        import os
        env_var_name = ciphertext.split("env:", 1)[1]
        return os.environ.get(env_var_name, "")

    settings = get_settings()
    key = _derive_fernet_key(settings.SECRET_KEY)
    fernet = Fernet(key)
    try:
        return fernet.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except (InvalidToken, Exception) as exc:
        raise ValueError(f"Failed to decrypt secret: {exc}") from exc
