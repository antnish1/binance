from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    log_level: str = "INFO"
    host: str = "127.0.0.1"
    port: int = 8000

    binance_symbol: str = "BTCUSDT"
    market_stale_after_ms: int = Field(default=5000, ge=100)
    portfolio_reconcile_seconds: int = Field(default=60, ge=10)

    binance_rest_base_url: str = "https://api.binance.com"
    binance_ws_base_url: str = "wss://stream.binance.com:9443/ws"
    binance_ws_api_url: str = "wss://ws-api.binance.com:443/ws-api/v3"
    binance_api_key: str | None = None
    binance_api_secret: str | None = None

    trading_enabled: bool = False

    @property
    def normalized_symbol(self) -> str:
        return self.binance_symbol.upper().strip()

    def assert_safe_startup(self) -> None:
        if self.trading_enabled:
            raise RuntimeError(
                "TRADING_ENABLED=true is blocked in this phase. Order execution has not been enabled."
            )


@lru_cache
def get_settings() -> Settings:
    return Settings()
