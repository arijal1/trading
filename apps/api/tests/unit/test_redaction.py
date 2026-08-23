from __future__ import annotations

import json
import logging

from app.core.logging import configure_logging, get_logger
from app.core.redaction import REDACTED, redact_processor, redact_value

SECRET = "sk-live-SUPERSECRET-do-not-leak"


def test_top_level_sensitive_keys_are_redacted():
    out = redact_processor(None, "info", {"api_key": SECRET, "symbol": "BTC/USD"})
    assert out["api_key"] == REDACTED
    assert out["symbol"] == "BTC/USD"


def test_matching_is_case_insensitive_and_substring():
    out = redact_processor(
        None,
        "info",
        {
            "API_SECRET": SECRET,
            "exchange_api_key": SECRET,
            "Authorization": "Bearer abc",
            "user_password": "hunter2",
            "request_signature": "deadbeef",
        },
    )
    assert all(v == REDACTED for v in out.values())


def test_nested_dicts_and_lists_are_redacted():
    event = {
        "payload": {"api_key": SECRET, "nested": {"token": SECRET, "safe": 1}},
        "items": [{"password": SECRET}, {"quantity": "0.5"}],
    }
    out = redact_processor(None, "info", event)
    assert out["payload"]["api_key"] == REDACTED
    assert out["payload"]["nested"]["token"] == REDACTED
    assert out["payload"]["nested"]["safe"] == 1
    assert out["items"][0]["password"] == REDACTED
    assert out["items"][1]["quantity"] == "0.5"


def test_non_sensitive_payload_is_untouched():
    event = {"event": "order_filled", "side": "BUY", "quantity": "1.5", "fee": "0.1"}
    assert redact_processor(None, "info", event) == event


def test_recursion_is_bounded():
    """A deeply nested (or pathological) payload must not blow the stack —
    logging can never be allowed to take the process down."""
    deep: dict = {"safe": 1}
    for _ in range(50):
        deep = {"level": deep}
    redact_value("level", deep)  # must not raise


def test_tuples_stay_tuples():
    out = redact_value("items", ({"token": SECRET}, {"n": 1}))
    assert isinstance(out, tuple)
    assert out[0]["token"] == REDACTED


def test_secret_never_reaches_actual_log_output(capsys):
    """End-to-end through the real configured logging stack, not just the
    processor in isolation."""
    configure_logging()
    logging.getLogger().setLevel(logging.INFO)
    logger = get_logger("redaction-test")
    logger.info("exchange_call", api_key=SECRET, symbol="BTC/USD")

    captured = capsys.readouterr().out
    assert SECRET not in captured
    assert REDACTED in captured
    # The useful, non-sensitive context must survive.
    assert "BTC/USD" in captured
    assert json.loads(captured.strip().splitlines()[-1])["symbol"] == "BTC/USD"
