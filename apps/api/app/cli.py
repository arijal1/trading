"""Operator CLI for out-of-band provisioning.

Exists to solve the auth bootstrap problem: `POST /auth/register` is
admin-gated, so the first admin cannot be created through the API. Doing
it here rather than via a self-service endpoint means a deployment never
has a window in which anyone can register themselves as admin.

    poetry run python -m app.cli create-admin admin@example.com
    poetry run python -m app.cli generate-keys

The password is read from a prompt (never an argv argument, which would
land in shell history and the process table).
"""
from __future__ import annotations

import argparse
import asyncio
import getpass
import secrets
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.crypto import generate_key
from app.core.security import hash_password
from app.db.models.core import User

MIN_PASSWORD_LENGTH = 12


async def _create_admin(email: str, password: str) -> int:
    settings = get_settings()
    engine = create_async_engine(settings.DATABASE_URL)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    try:
        async with session_factory() as db:
            existing = await db.execute(select(User).where(User.email == email))
            if existing.scalar_one_or_none() is not None:
                print(f"error: a user with email {email!r} already exists", file=sys.stderr)
                return 1
            db.add(
                User(email=email, hashed_password=hash_password(password), role="admin")
            )
            await db.commit()
        print(f"created admin user {email!r}")
        return 0
    finally:
        await engine.dispose()


def _cmd_create_admin(args: argparse.Namespace) -> int:
    password = getpass.getpass("Password: ")
    if len(password) < MIN_PASSWORD_LENGTH:
        print(
            f"error: password must be at least {MIN_PASSWORD_LENGTH} characters",
            file=sys.stderr,
        )
        return 1
    if password != getpass.getpass("Confirm password: "):
        print("error: passwords do not match", file=sys.stderr)
        return 1
    return asyncio.run(_create_admin(args.email, password))


def _cmd_generate_keys(_args: argparse.Namespace) -> int:
    print("# Add these to your .env — treat both as production secrets.")
    print(f"MASTER_ENCRYPTION_KEY={generate_key()}")
    print(f"JWT_SECRET_KEY={secrets.token_urlsafe(48)}")
    return 0


async def _seed_demo() -> int:
    """Create the minimum rows needed for the dashboard to show something.

    Exists because there is no onboarding endpoint yet (see
    docs/API_DESIGN.md): without this, a fresh install has no exchange,
    market, or account, so the dashboard renders empty and the paper-tick
    endpoint has nothing to tick. Idempotent — safe to re-run.

    Creates a *paper* account only. Nothing here can touch real money.
    """
    from decimal import Decimal

    from app.db.models.core import Account, Asset, Exchange, Market, User

    settings = get_settings()
    engine = create_async_engine(settings.DATABASE_URL)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    try:
        async with session_factory() as db:
            user = (
                await db.execute(select(User).where(User.email == "demo@localhost"))
            ).scalar_one_or_none()
            if user is None:
                # Unusable password: this account is a data owner, not a
                # login. Real logins come from `create-admin`.
                user = User(
                    email="demo@localhost", hashed_password="!", role="user"
                )
                db.add(user)
                await db.flush()

            exchange = (
                await db.execute(select(Exchange).where(Exchange.name == "Mock Exchange"))
            ).scalar_one_or_none()
            if exchange is None:
                exchange = Exchange(name="Mock Exchange", adapter_type="mock")
                db.add(exchange)
                await db.flush()

            assets: dict[str, Asset] = {}
            for symbol in ("BTC", "ETH", "USD"):
                asset = (
                    await db.execute(select(Asset).where(Asset.symbol == symbol))
                ).scalar_one_or_none()
                if asset is None:
                    asset = Asset(symbol=symbol)
                    db.add(asset)
                    await db.flush()
                assets[symbol] = asset

            for base in ("BTC", "ETH"):
                symbol = f"{base}/USD"
                market = (
                    await db.execute(select(Market).where(Market.symbol == symbol))
                ).scalar_one_or_none()
                if market is None:
                    db.add(
                        Market(
                            exchange_id=exchange.id,
                            base_asset_id=assets[base].id,
                            quote_asset_id=assets["USD"].id,
                            symbol=symbol,
                        )
                    )

            account = (
                await db.execute(
                    select(Account).where(Account.name == "Demo Paper Account")
                )
            ).scalar_one_or_none()
            if account is None:
                account = Account(
                    user_id=user.id,
                    name="Demo Paper Account",
                    mode="paper",
                    starting_equity=Decimal("10000"),
                )
                db.add(account)

            await db.commit()
            await db.refresh(account)

        print("Seeded demo data:")
        print("  exchange : Mock Exchange")
        print("  markets  : BTC/USD, ETH/USD")
        print(f"  account  : Demo Paper Account (paper, $10,000)  id={account.id}")
        print()
        print("Next: sync candles, then run a tick from the dashboard.")
        return 0
    finally:
        await engine.dispose()


def _cmd_seed_demo(_args: argparse.Namespace) -> int:
    return asyncio.run(_seed_demo())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.cli", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    create_admin = sub.add_parser("create-admin", help="Create the initial admin user")
    create_admin.add_argument("email")
    create_admin.set_defaults(func=_cmd_create_admin)

    gen = sub.add_parser("generate-keys", help="Generate encryption/JWT secrets")
    gen.set_defaults(func=_cmd_generate_keys)

    seed = sub.add_parser(
        "seed-demo", help="Create a demo paper account, exchange, and markets"
    )
    seed.set_defaults(func=_cmd_seed_demo)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover - entrypoint
    raise SystemExit(main())
