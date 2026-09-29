from decimal import Decimal
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
    binance_base_asset: str = "BTC"
    binance_quote_asset: str = "USDT"
    market_stale_after_ms: int = Field(default=5000, ge=100)
    portfolio_reconcile_seconds: int = Field(default=60, ge=10)

    binance_rest_base_url: str = "https://api.binance.com"
    binance_ws_base_url: str = "wss://stream.binance.com:9443/ws"
    binance_ws_api_url: str = "wss://ws-api.binance.com:443/ws-api/v3"
    binance_api_key: str | None = None
    binance_api_secret: str | None = None

    risk_max_order_notional: Decimal = Field(default=Decimal(25), gt=0)
    risk_max_position_notional: Decimal = Field(default=Decimal(100), gt=0)
    risk_max_daily_loss: Decimal = Field(default=Decimal(10), gt=0)
    risk_max_open_orders: int = Field(default=3, ge=1)
    risk_max_orders_per_minute: int = Field(default=10, ge=1)

    paper_starting_quote_balance: Decimal = Field(default=Decimal(1000), gt=0)
    paper_fee_bps: Decimal = Field(default=Decimal(10), ge=0)
    paper_slippage_bps: Decimal = Field(default=Decimal(2), ge=0)

    recording_enabled: bool = True
    recording_max_events: int = Field(default=100000, ge=1000)
    recording_path: str | None = "/tmp/binance-market.jsonl"
    replay_max_events: int = Field(default=50000, ge=100)

    trading_enabled: bool = False

    @property
    def normalized_symbol(self) -> str:
        return self.binance_symbol.upper().strip()

    @property
    def normalized_base_asset(self) -> str:
        return self.binance_base_asset.upper().strip()

    @property
    def normalized_quote_asset(self) -> str:
        return self.binance_quote_asset.upper().strip()

    def assert_safe_startup(self) -> None:
        if self.trading_enabled:
            raise RuntimeError(
                "TRADING_ENABLED=true is blocked in this phase. Live order execution is not enabled."
            )


@lru_cache
def get_settings() -> Settings:
    return Settings()
