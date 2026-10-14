"""Tests for secret encryption and reference handling."""

import os
import pytest
from backend.app.core.security import encrypt_secret, decrypt_secret


def test_encrypt_and_decrypt_secret():
    raw_secret = "test_hunter_api_key_12345"
    encrypted = encrypt_secret(raw_secret)
    assert encrypted != raw_secret
    assert len(encrypted) > 20

    decrypted = decrypt_secret(encrypted)
    assert decrypted == raw_secret


def test_decrypt_env_reference(monkeypatch):
    monkeypatch.setenv("TEST_PROVIDER_KEY", "secret_env_value_999")
    resolved = decrypt_secret("env:TEST_PROVIDER_KEY")
    assert resolved == "secret_env_value_999"


def test_decrypt_empty_string():
    assert decrypt_secret("") == ""
    assert encrypt_secret("") == ""


def test_decrypt_invalid_ciphertext():
    with pytest.raises(ValueError, match="Failed to decrypt secret"):
        decrypt_secret("invalid_corrupted_ciphertext")
