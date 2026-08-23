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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.cli", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    create_admin = sub.add_parser("create-admin", help="Create the initial admin user")
    create_admin.add_argument("email")
    create_admin.set_defaults(func=_cmd_create_admin)

    gen = sub.add_parser("generate-keys", help="Generate encryption/JWT secrets")
    gen.set_defaults(func=_cmd_generate_keys)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover - entrypoint
    raise SystemExit(main())
