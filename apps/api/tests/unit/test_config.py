from app.core.config import Settings, TradingMode


def test_defaults_are_safe():
    settings = Settings(_env_file=None)
    assert settings.TRADING_MODE == TradingMode.PAPER
    assert settings.LIVE_TRADING is False
    assert settings.DISABLE_WITHDRAWALS is True


def test_live_trading_requires_every_guardrail():
    settings = Settings(_env_file=None)
    assert settings.live_trading_allowed() is False

    settings = Settings(
        _env_file=None,
        TRADING_MODE=TradingMode.LIVE,
        LIVE_TRADING=True,
        TRADING_CONFIRMATION=True,
        VALID_EXCHANGE_CREDENTIALS=True,
        RISK_LIMITS_VALID=True,
        EMERGENCY_STOP_AVAILABLE=True,
    )
    assert settings.live_trading_allowed() is True

    settings = Settings(
        _env_file=None,
        TRADING_MODE=TradingMode.LIVE,
        LIVE_TRADING=True,
        TRADING_CONFIRMATION=True,
        VALID_EXCHANGE_CREDENTIALS=False,
        RISK_LIMITS_VALID=True,
        EMERGENCY_STOP_AVAILABLE=True,
    )
    assert settings.live_trading_allowed() is False


def test_take_profit_levels_parses_csv():
    settings = Settings(_env_file=None, TAKE_PROFIT_LEVELS="0.1,0.2,0.3")
    assert settings.take_profit_levels == [0.1, 0.2, 0.3]
