"""Security and cryptographic utilities for secret references and token encryption."""

import base64
import hashlib
import secrets

from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

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
    except (InvalidToken, UnicodeDecodeError, ValueError):
        # Keep ciphertext/provider exception details out of API errors and logs.
        raise ValueError("Failed to decrypt secret") from None


profile_bearer = HTTPBearer(auto_error=False, scheme_name="ProfileBearer")


async def require_api_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Security(profile_bearer),
) -> None:
    """Replaceable single-user authentication boundary; never logs credentials."""
    configured = get_settings().JOB_AGENT_API_TOKEN
    token = configured.get_secret_value() if configured else ""
    if not token.strip():
        raise HTTPException(503, "Profile API authentication is not configured")
    if len(request.headers.getlist("Authorization")) > 1:
        raise HTTPException(401, "Ambiguous bearer credentials")
    authorization = request.headers.get("Authorization", "")
    scheme, _, supplied = authorization.partition(" ")
    if scheme.lower() != "bearer" or not supplied or not secrets.compare_digest(
        supplied.encode("utf-8"), token.encode("utf-8")
    ):
        raise HTTPException(401, "Invalid or missing bearer token", headers={"WWW-Authenticate": "Bearer"})
