import pytest

from trading_bot.config import Settings


def test_live_trading_flag_is_blocked():
    settings = Settings(trading_enabled=True)
    with pytest.raises(RuntimeError):
        settings.assert_safe_startup()
