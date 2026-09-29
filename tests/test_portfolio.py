import asyncio

from trading_bot.portfolio import PortfolioState


def test_portfolio_reconcile_and_user_events() -> None:
    async def run() -> None:
        state = PortfolioState()
        await state.replace_from_account(
            {"balances": [{"asset": "USDT", "free": "10", "locked": "2"}]},
            100,
        )
        await state.replace_open_orders(
            [
                {
                    "symbol": "BTCUSDT",
                    "orderId": 1,
                    "clientOrderId": "abc",
                    "side": "BUY",
                    "type": "LIMIT",
                    "status": "NEW",
                    "price": "100",
                    "origQty": "0.1",
                    "executedQty": "0",
                }
            ],
            100,
        )
        await state.apply_account_position(
            {"E": 110, "B": [{"a": "USDT", "f": "9", "l": "3"}]}
        )
        await state.apply_execution_report(
            {
                "E": 120,
                "s": "BTCUSDT",
                "i": 1,
                "c": "abc",
                "S": "BUY",
                "o": "LIMIT",
                "X": "PARTIALLY_FILLED",
                "p": "100",
                "q": "0.1",
                "z": "0.04",
            }
        )
        snap = await state.snapshot()
        assert snap["balances"][0]["total"] == "12"
        assert snap["open_orders"][0]["status"] == "PARTIALLY_FILLED"
        assert snap["open_orders"][0]["executed_qty"] == "0.04"
        await state.apply_execution_report(
            {
                "E": 130,
                "s": "BTCUSDT",
                "i": 1,
                "c": "abc",
                "S": "BUY",
                "o": "LIMIT",
                "X": "FILLED",
                "p": "100",
                "q": "0.1",
                "z": "0.1",
            }
        )
        snap = await state.snapshot()
        assert snap["open_orders"] == []

    asyncio.run(run())
