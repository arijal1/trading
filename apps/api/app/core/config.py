"""Central runtime configuration.

Every value here is documented in `.env.example` at the repo root. Nothing
in this module ever holds a real secret as its default — defaults are safe
placeholders or the most conservative value (e.g. TRADING_MODE=paper,
LIVE_TRADING=false).
"""
from __future__ import annotations

from enum import StrEnum
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class TradingMode(StrEnum):
    PAPER = "paper"
    SHADOW = "shadow"
    LIVE = "live"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Core service ---
    APP_NAME: str = "trading-api"
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"
    LOG_JSON: bool = True

    DATABASE_URL: str = "postgresql+asyncpg://trading:trading@localhost:5432/trading"
    REDIS_URL: str = "redis://localhost:6379/0"

    # --- CORS (Phase 5: the Next.js dashboard fetches this API directly
    # from the browser, a different origin) ---
    CORS_ALLOWED_ORIGINS: str = "http://localhost:3000,http://127.0.0.1:3000"

    # --- Trading mode (Section 3) ---
    TRADING_MODE: TradingMode = TradingMode.PAPER

    # --- Live-trading guardrails (Section 39) ---
    LIVE_TRADING: bool = False
    TRADING_CONFIRMATION: bool = False
    VALID_EXCHANGE_CREDENTIALS: bool = False
    RISK_LIMITS_VALID: bool = False
    EMERGENCY_STOP_AVAILABLE: bool = True
    MAX_LIVE_CAPITAL: float = 1000.0
    DISABLE_WITHDRAWALS: bool = True

    # --- Capital recovery / profit management (Section 2) ---
    INITIAL_CAPITAL_RECOVERY_ENABLED: bool = True
    INITIAL_CAPITAL_RECOVERY_TARGET: float = 1.00
    MIN_PROFIT_BEFORE_CAPITAL_RECOVERY: float = 0.15
    PROFIT_POSITION_ENABLED: bool = True
    TRAILING_STOP_PERCENT: float = 0.05
    MIN_POSITION_VALUE: float = 10.0
    MAX_SLIPPAGE_PERCENT: float = 0.01
    TAKE_PROFIT_LEVELS: str = "0.10,0.25,0.50"  # comma-separated fractions

    # --- Token risk (Section 9) ---
    MAX_TOKEN_RISK_SCORE: int = 60

    # --- Copy trading (Sections 11-13, 41) ---
    MIN_TRADER_SCORE: float = 0.6
    MAX_COPY_ALLOCATION_PER_TRADER: float = 0.05
    MAX_NUMBER_OF_COPIED_TRADERS: int = 10
    MAX_COPIED_POSITION_SIZE: float = 0.01
    MAX_TOTAL_COPY_EXPOSURE: float = 0.20
    MAX_COPY_PRICE_DEVIATION_PERCENT: float = 0.03
    MIN_CONSENSUS_DIFFERENCE: float = 0.15

    # --- Portfolio risk limits (Section 21) ---
    MAX_DAILY_LOSS: float = 0.05
    MAX_WEEKLY_LOSS: float = 0.12
    MAX_DRAWDOWN: float = 0.20
    MAX_POSITION_SIZE: float = 0.10
    MAX_PORTFOLIO_EXPOSURE: float = 0.80
    MAX_ASSET_CONCENTRATION: float = 0.25
    MAX_COPY_TRADING_EXPOSURE: float = 0.20
    MAX_OPEN_POSITIONS: int = 20
    EMERGENCY_CLOSE_POSITIONS_ON_BREACH: bool = False

    # --- Data quality (Section 52) ---
    MAX_DATA_AGE_MS: int = 60_000

    # --- Notifications ---
    TELEGRAM_BOT_TOKEN: str | None = None
    TELEGRAM_CHAT_ID: str | None = None

    # --- AI provider (Section 50) ---
    ANTHROPIC_API_KEY: str | None = None
    OPENAI_API_KEY: str | None = None
    AI_MODEL_VERSION: str = "unset"

    # --- Secrets at rest (Phase 6) ---
    # Fernet key for encrypting exchange API credentials in the database.
    # No default: there is deliberately no "encryption off" fallback, so a
    # deployment that forgets to set this fails loudly at the point of use
    # rather than silently storing exchange keys in plaintext.
    MASTER_ENCRYPTION_KEY: str | None = None

    # --- Auth (Phase 6) ---
    # Also no default: an unset secret must not silently become a
    # well-known signing key that anyone could forge admin tokens with.
    JWT_SECRET_KEY: str | None = None
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60
    # Defaults false so Phase 1-5 endpoints and the dashboard keep working
    # unchanged; turning auth on is a deliberate deployment decision.
    # See docs/AUTH.md — with this false the API is unauthenticated and
    # must not be exposed beyond a trusted network.
    AUTH_REQUIRED: bool = False

    @property
    def take_profit_levels(self) -> list[float]:
        return [float(x) for x in self.TAKE_PROFIT_LEVELS.split(",") if x.strip()]

    @property
    def cors_allowed_origins(self) -> list[str]:
        return [x.strip() for x in self.CORS_ALLOWED_ORIGINS.split(",") if x.strip()]

    def live_trading_allowed(self) -> bool:
        """All Section 39 guardrails must hold before any live order path is enabled."""
        return all(
            [
                self.TRADING_MODE == TradingMode.LIVE,
                self.LIVE_TRADING,
                self.TRADING_CONFIRMATION,
                self.VALID_EXCHANGE_CREDENTIALS,
                self.RISK_LIMITS_VALID,
                self.EMERGENCY_STOP_AVAILABLE,
            ]
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
