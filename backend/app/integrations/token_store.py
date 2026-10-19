"""Versioned, context-bound Fernet envelopes with explicit key identity checks."""

import hashlib
import json
import re

from cryptography.fernet import Fernet, InvalidToken


class ConnectionError(ValueError):
    """Only fixed error codes cross an API/log boundary."""


class TokenStore:
    def __init__(self, settings):
        self.active = settings.OAUTH_ACTIVE_KEY_ID
        self.keys = settings.OAUTH_ENCRYPTION_KEYS
        if not self.active or self.active not in self.keys:
            raise ConnectionError("oauth_encryption_not_configured")
        for key_id, key in self.keys.items():
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", key_id):
                raise ConnectionError("invalid_encryption_key_id")
            try:
                Fernet(key.get_secret_value().encode())
            except (ValueError, TypeError):
                raise ConnectionError("invalid_encryption_key") from None

    def encrypt(self, value, purpose):
        key = self.keys[self.active].get_secret_value().encode()
        fingerprint = hashlib.sha256(key).hexdigest()[:24]
        payload = json.dumps({"purpose": purpose, "value": value}).encode()
        return f"{self.active}:{fingerprint}:" + Fernet(key).encrypt(payload).decode()

    def decrypt(self, envelope, purpose):
        try:
            key_id, fingerprint, ciphertext = envelope.split(":", 2)
            key = self.keys[key_id].get_secret_value().encode()
            if fingerprint != hashlib.sha256(key).hexdigest()[:24]:
                raise ConnectionError("encryption_key_changed")
            payload = json.loads(Fernet(key).decrypt(ciphertext.encode()))
            if payload["purpose"] != purpose:
                raise ConnectionError("token_context_mismatch")
            return payload["value"]
        except (InvalidToken, KeyError, ValueError, TypeError, AttributeError):
            raise ConnectionError("token_decryption_failed") from None
