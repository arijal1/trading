"""Symmetric encryption for secrets at rest (brief Section 46).

Exchange API credentials are the highest-value secret this system holds:
an attacker with them can trade (and, without the withdrawal restriction
the brief mandates, potentially withdraw) against a real account. They are
therefore never stored in plaintext, and this module is the only path
that encrypts or decrypts them.

Two deliberate "fail loudly" choices:

- **No plaintext fallback.** If `MASTER_ENCRYPTION_KEY` is unset, this
  raises rather than storing the credential unencrypted. A silent
  fallback is how plaintext secrets end up in a production database.
- **No key derivation from a weak passphrase.** The setting must be a
  real Fernet key (32 url-safe base64 bytes, i.e. what
  `Fernet.generate_key()` produces). Accepting an arbitrary short string
  and stretching it would invite `MASTER_ENCRYPTION_KEY=changeme`.

Fernet (AES-128-CBC + HMAC-SHA256, with an authenticated timestamp) is
used rather than raw AES: it is authenticated, so a tampered ciphertext
fails to decrypt instead of yielding attacker-controlled plaintext.
"""
from __future__ import annotations

from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings


class EncryptionNotConfiguredError(RuntimeError):
    """MASTER_ENCRYPTION_KEY is unset or is not a valid Fernet key."""


class DecryptionError(ValueError):
    """Ciphertext could not be decrypted (wrong key, or tampered-with)."""


def generate_key() -> str:
    """Generate a new Fernet key. For operator use when provisioning."""
    return Fernet.generate_key().decode()


@lru_cache
def _fernet() -> Fernet:
    settings = get_settings()
    raw = settings.MASTER_ENCRYPTION_KEY
    if not raw:
        raise EncryptionNotConfiguredError(
            "MASTER_ENCRYPTION_KEY is not set. Exchange credentials cannot be "
            "stored or read without it — refusing to fall back to plaintext. "
            "Generate one with: python -c "
            "'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
        )
    try:
        return Fernet(raw.encode())
    except (ValueError, TypeError) as exc:
        raise EncryptionNotConfiguredError(
            "MASTER_ENCRYPTION_KEY is not a valid Fernet key (expected 32 "
            "url-safe base64-encoded bytes)"
        ) from exc


def encrypt_secret(plaintext: str) -> str:
    """Encrypt a secret for storage. Never logs its input or output."""
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_secret(ciphertext: str) -> str:
    """Decrypt a stored secret. Never logs its input or output."""
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise DecryptionError(
            "could not decrypt stored secret — the value was encrypted with a "
            "different MASTER_ENCRYPTION_KEY, or has been tampered with"
        ) from exc


def reset_cache() -> None:
    """Clear the memoized Fernet. Only for tests that swap the key."""
    _fernet.cache_clear()
