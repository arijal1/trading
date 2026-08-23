"""Secret redaction for structured logs (brief Sections 34, 46).

A defence-in-depth layer, not the primary control. The primary control is
that no code passes a secret to a log call in the first place (see
`app/services/exchanges/credentials.py`, which logs the *fact* of a
credential change and never the credential). This processor exists
because "no code ever does X" is a claim that decays as a codebase grows,
and a leaked API key in a log aggregator is not recoverable after the fact.

Matching is on the *key name*, substring and case-insensitive, so
`api_key`, `API_SECRET`, `exchange_api_key`, and `Authorization` all
redact. Values are never inspected: pattern-matching log values to guess
what looks secret is both slow and unreliable, and would still miss a
credential that happens not to match the pattern.
"""
from __future__ import annotations

from typing import Any

REDACTED = "***REDACTED***"

# Substrings that mark a key as sensitive. Deliberately broad: a
# false-positive redaction costs a slightly less useful log line, while a
# false negative costs a leaked credential.
SENSITIVE_KEY_PARTS: tuple[str, ...] = (
    "api_key",
    "apikey",
    "api_secret",
    "apisecret",
    "secret",
    "password",
    "passwd",
    "token",
    "authorization",
    "auth_header",
    "signature",
    "private_key",
    "credential",
    "cookie",
    "session_id",
)

# Bounds recursion so a pathological/cyclic structure in a log payload
# can't hang the logging path — logging must never be able to take the
# process down.
_MAX_DEPTH = 6


def _is_sensitive(key: str) -> bool:
    lowered = key.lower()
    return any(part in lowered for part in SENSITIVE_KEY_PARTS)


def redact_value(key: str, value: Any, depth: int = 0) -> Any:
    if _is_sensitive(key):
        return REDACTED
    if depth >= _MAX_DEPTH:
        return value
    if isinstance(value, dict):
        return {k: redact_value(str(k), v, depth + 1) for k, v in value.items()}
    if isinstance(value, list | tuple):
        rebuilt = [redact_value(key, v, depth + 1) for v in value]
        return type(value)(rebuilt) if isinstance(value, tuple) else rebuilt
    return value


def redact_processor(_logger: Any, _method_name: str, event_dict: dict) -> dict:
    """structlog processor: redact sensitive keys anywhere in the event."""
    return {k: redact_value(str(k), v) for k, v in event_dict.items()}
