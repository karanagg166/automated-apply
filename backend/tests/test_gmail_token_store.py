"""OAuth encryption is independent of the legacy development SECRET_KEY."""

import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr

from backend.app.integrations.token_store import ConnectionError, TokenStore
from backend.tests.phase4a_fakes import oauth_settings


def test_token_encryption_context_and_no_plaintext():
    store = TokenStore(oauth_settings())
    encrypted = store.encrypt("fictional-sensitive-refresh", "account-id:refresh")
    assert "fictional-sensitive-refresh" not in encrypted
    assert (
        store.decrypt(encrypted, "account-id:refresh") == "fictional-sensitive-refresh"
    )
    with pytest.raises(ConnectionError):
        store.decrypt(encrypted, "other-account:refresh")
    with pytest.raises(ConnectionError):
        store.decrypt(encrypted[:-8] + "tampered", "account-id:refresh")


def test_key_rotation_and_accidental_key_change():
    settings = oauth_settings()
    envelope = TokenStore(settings).encrypt("refresh", "account")
    settings.OAUTH_ENCRYPTION_KEYS["test-v2"] = SecretStr(
        Fernet.generate_key().decode()
    )
    settings.OAUTH_ACTIVE_KEY_ID = "test-v2"
    assert TokenStore(settings).decrypt(envelope, "account") == "refresh"
    settings.OAUTH_ENCRYPTION_KEYS["test-v1"] = SecretStr(
        Fernet.generate_key().decode()
    )
    with pytest.raises(ConnectionError):
        TokenStore(settings).decrypt(envelope, "account")
    assert envelope.startswith("test-v1:")


@pytest.mark.parametrize(
    "keys,active",
    [
        ({}, None),
        ({"v1": "insecure-password"}, "v1"),
        ({"v1": Fernet.generate_key().decode()}, "missing"),
    ],
)
def test_missing_or_insecure_encryption_fails_closed(keys, active):
    settings = oauth_settings()
    settings.OAUTH_ENCRYPTION_KEYS = {k: SecretStr(v) for k, v in keys.items()}
    settings.OAUTH_ACTIVE_KEY_ID = active
    with pytest.raises(ConnectionError):
        TokenStore(settings)
