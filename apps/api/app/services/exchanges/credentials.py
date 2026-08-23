"""Exchange API credential storage (brief Sections 39, 46).

Wraps `app.core.crypto` around the `exchanges.api_key_encrypted` /
`api_secret_encrypted` columns. Every read returns a `ExchangeCredentials`
value object whose `__repr__` is redacted, so a credential that reaches a
log line, a traceback, or a debugger by accident does not print the
secret.

`withdrawals_disabled` is stored alongside and checked here rather than
only at order time: the brief (Section 39) requires that live trading be
impossible against an API key that carries withdrawal permission, and the
cheapest place to enforce that is the moment credentials are registered.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import decrypt_secret, encrypt_secret
from app.core.logging import get_logger
from app.db.models.core import Exchange

logger = get_logger(__name__)


class CredentialsNotConfiguredError(RuntimeError):
    """The exchange row has no stored API credentials."""


class WithdrawalPermissionError(RuntimeError):
    """Refusing to register credentials that are not withdrawal-restricted."""


@dataclass(frozen=True)
class ExchangeCredentials:
    api_key: str
    api_secret: str

    def __repr__(self) -> str:  # pragma: no cover - trivial, but security-relevant
        return "ExchangeCredentials(api_key='***', api_secret='***')"

    __str__ = __repr__


async def store_credentials(
    db: AsyncSession,
    *,
    exchange: Exchange,
    api_key: str,
    api_secret: str,
    withdrawals_disabled: bool,
) -> Exchange:
    """Encrypt and persist credentials for an exchange.

    Refuses outright if the caller cannot attest that the key is
    withdrawal-restricted. This is an attestation, not a verification —
    only the exchange can actually tell us a key's permissions, and no
    real adapter exists yet to ask. Documented as such rather than
    implying a guarantee this code cannot make.
    """
    if not withdrawals_disabled:
        raise WithdrawalPermissionError(
            f"refusing to store credentials for exchange {exchange.name!r} that are not "
            "attested withdrawal-restricted (brief Section 39: live trading must never "
            "run against an API key permitted to withdraw funds)"
        )

    exchange.api_key_encrypted = encrypt_secret(api_key)
    exchange.api_secret_encrypted = encrypt_secret(api_secret)
    exchange.withdrawals_disabled = True
    await db.commit()
    await db.refresh(exchange)

    # Deliberately logs the *fact* of a credential change (Section 33
    # auditability) and never any part of the credential itself.
    logger.info("exchange_credentials_stored", exchange_id=str(exchange.id), name=exchange.name)
    return exchange


async def load_credentials(db: AsyncSession, exchange_id: uuid.UUID) -> ExchangeCredentials:
    exchange = await db.get(Exchange, exchange_id)
    if exchange is None:
        raise CredentialsNotConfiguredError(f"exchange {exchange_id} not found")
    return credentials_from(exchange)


def credentials_from(exchange: Exchange) -> ExchangeCredentials:
    if not exchange.api_key_encrypted or not exchange.api_secret_encrypted:
        raise CredentialsNotConfiguredError(
            f"exchange {exchange.name!r} has no stored API credentials"
        )
    return ExchangeCredentials(
        api_key=decrypt_secret(exchange.api_key_encrypted),
        api_secret=decrypt_secret(exchange.api_secret_encrypted),
    )


def has_credentials(exchange: Exchange) -> bool:
    return bool(exchange.api_key_encrypted and exchange.api_secret_encrypted)
