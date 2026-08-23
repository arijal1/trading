from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from app.core import crypto
from app.core.config import Settings, get_settings


@pytest.fixture
def with_key(monkeypatch):
    """Point get_settings at a Settings carrying a real generated key."""
    key = Fernet.generate_key().decode()
    settings = Settings(MASTER_ENCRYPTION_KEY=key)
    monkeypatch.setattr(crypto, "get_settings", lambda: settings)
    crypto.reset_cache()
    yield key
    crypto.reset_cache()


def test_round_trip(with_key):
    secret = "sk-live-abc123-not-a-real-key"
    ciphertext = crypto.encrypt_secret(secret)
    assert ciphertext != secret
    assert secret not in ciphertext
    assert crypto.decrypt_secret(ciphertext) == secret


def test_ciphertext_differs_between_calls(with_key):
    """Fernet embeds a random IV, so encrypting the same value twice must
    not produce identical ciphertext — otherwise equal secrets would be
    identifiable by comparing stored rows."""
    a = crypto.encrypt_secret("same-value")
    b = crypto.encrypt_secret("same-value")
    assert a != b
    assert crypto.decrypt_secret(a) == crypto.decrypt_secret(b) == "same-value"


def test_missing_key_raises_rather_than_storing_plaintext(monkeypatch):
    settings = Settings(MASTER_ENCRYPTION_KEY=None)
    monkeypatch.setattr(crypto, "get_settings", lambda: settings)
    crypto.reset_cache()
    with pytest.raises(crypto.EncryptionNotConfiguredError, match="not set"):
        crypto.encrypt_secret("anything")
    crypto.reset_cache()


def test_invalid_key_raises(monkeypatch):
    settings = Settings(MASTER_ENCRYPTION_KEY="not-a-valid-fernet-key")
    monkeypatch.setattr(crypto, "get_settings", lambda: settings)
    crypto.reset_cache()
    with pytest.raises(crypto.EncryptionNotConfiguredError, match="not a valid Fernet key"):
        crypto.encrypt_secret("anything")
    crypto.reset_cache()


def test_decrypting_with_a_different_key_fails_loudly(with_key, monkeypatch):
    ciphertext = crypto.encrypt_secret("original-secret")

    other = Settings(MASTER_ENCRYPTION_KEY=Fernet.generate_key().decode())
    monkeypatch.setattr(crypto, "get_settings", lambda: other)
    crypto.reset_cache()

    with pytest.raises(crypto.DecryptionError, match="different MASTER_ENCRYPTION_KEY"):
        crypto.decrypt_secret(ciphertext)
    crypto.reset_cache()


def test_tampered_ciphertext_fails_rather_than_returning_garbage(with_key):
    """Fernet is authenticated: flipping a byte must fail the HMAC rather
    than decrypt to attacker-influenced plaintext."""
    ciphertext = crypto.encrypt_secret("original-secret")
    tampered = ciphertext[:-4] + ("AAAA" if not ciphertext.endswith("AAAA") else "BBBB")
    with pytest.raises(crypto.DecryptionError):
        crypto.decrypt_secret(tampered)


def test_generate_key_produces_a_usable_key():
    assert Fernet(crypto.generate_key().encode()) is not None


def test_real_settings_default_has_no_encryption_key():
    """The shipped default must not carry a baked-in key — a default key
    is the same as no encryption."""
    assert get_settings().MASTER_ENCRYPTION_KEY is None
