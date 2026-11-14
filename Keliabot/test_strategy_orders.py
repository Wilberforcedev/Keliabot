"""Offline stub tests for the Spot entry -> OCO sequencing in main.py.

The strategy modules need python-binance, ta, pandas and numpy, so this module
skips itself when those imports fail instead of breaking a stdlib-only run.
"""
import unittest


class _Client:
    """Minimal Spot client stub; records calls and replays order statuses."""

    def __init__(self, statuses, executed="0.00040000", fail_poll=False, fail_oco=0, fail_flatten=False):
        self.statuses = list(statuses)
        self.executed = executed
        self.fail_poll = fail_poll
        self.oco_failures_left = fail_oco
        self.fail_flatten = fail_flatten
        self.calls = []

    def get_symbol_ticker(self, **kwargs):
        return {"price": "50000.0"}

    def get_exchange_info(self):
        return {"symbols": [{"symbol": "BTCUSDT", "filters": [
            {"filterType": "PRICE_FILTER", "tickSize": "0.01000000"},
            {"filterType": "LOT_SIZE", "stepSize": "0.00001000"},
        ]}]}

    def order_limit_buy(self, **kwargs):
        self.calls.append(("order_limit_buy", kwargs))
        return {"orderId": 111, "status": "NEW"}

    def order_limit_sell(self, **kwargs):
        self.calls.append(("order_limit_sell", kwargs))
        return {"orderId": 111, "status": "NEW"}

    def get_order(self, **kwargs):
        self.calls.append(("get_order", kwargs))
        if self.fail_poll:
            raise self.exc(-1001, "disconnected")
        status = self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]
        executed = self.executed if status in ("FILLED", "PARTIALLY_FILLED") else "0.00000000"
        return {"orderId": 111, "status": status, "executedQty": executed}

    def cancel_order(self, **kwargs):
        self.calls.append(("cancel_order", kwargs))
        return {"status": "CANCELED"}

    def order_oco_sell(self, **kwargs):
        self.calls.append(("order_oco_sell", kwargs))
        if self.oco_failures_left:
            self.oco_failures_left -= 1
            raise self.exc(-2010, "insufficient balance")
        return {"ok": "oco_sell"}

    def order_oco_buy(self, **kwargs):
        self.calls.append(("order_oco_buy", kwargs))
        if self.oco_failures_left:
            self.oco_failures_left -= 1
            raise self.exc(-2010, "insufficient balance")
        return {"ok": "oco_buy"}

    def order_market(self, **kwargs):
        self.calls.append(("order_market", kwargs))
        if self.fail_flatten:
            raise self.exc(-2010, "insufficient balance")
        return {"ok": "market"}

    def names(self):
        return [name for name, _ in self.calls]

    def params(self, name):
        for called, kwargs in self.calls:
            if called == name:
                return kwargs
        return None


class SpotSequencingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import binance_clients
            import main
        except ImportError as error:
            raise unittest.SkipTest(f"strategy dependencies unavailable: {error}")
        cls.main = main
        cls.binance_clients = binance_clients

    def setUp(self):
        self.saved = (
            self.main.sleep,
            self.main.monotonic,
            self.main.create_spot_client,
            self.main.create_public_market_client,
            self.binance_clients.ALLOW_ORDERS,
        )
        self.clock = 0.0
        self.sleeps = []
        self.main.sleep = self.fake_sleep
        self.main.monotonic = lambda: self.clock
        self.binance_clients.ALLOW_ORDERS = True

    def tearDown(self):
        (
            self.main.sleep,
            self.main.monotonic,
            self.main.create_spot_client,
            self.main.create_public_market_client,
            self.binance_clients.ALLOW_ORDERS,
        ) = self.saved

    def fake_sleep(self, seconds):
        self.sleeps.append(seconds)
        self.clock += seconds

    def make_bot(self, client):
        client.exc = self.make_exc
        self.main.create_spot_client = lambda: client
        self.main.create_public_market_client = lambda: _Client(["NEW"])
        return self.main.TradingBot()

    def make_exc(self, code, message):
        return self.main.BinanceAPIException(None, code, '{{"code":{},"msg":"{}"}}'.format(code, message))

    def test_oco_waits_for_entry_fill(self):
        client = _Client(["NEW", "NEW", "FILLED"])
        bot = self.make_bot(client)

        self.assertTrue(bot.open_order("BTCUSDT", "buy", 20.0))

        names = client.names()
        self.assertEqual(names[:2], ["order_limit_buy", "get_order"])
        self.assertEqual(names.count("get_order"), 3)
        self.assertGreater(names.index("order_oco_sell"), names.index("get_order"))
        self.assertEqual(self.sleeps, [2, 2])

    def test_oco_uses_executed_quantity(self):
        client = _Client(["FILLED"], executed="0.00040000")
        bot = self.make_bot(client)

        bot.open_order("BTCUSDT", "buy", 20.0)

        self.assertEqual(client.params("order_oco_sell")["quantity"], "0.0004")

    def test_long_oco_prices_straddle_entry(self):
        client = _Client(["FILLED"])
        bot = self.make_bot(client)

        bot.open_order("BTCUSDT", "buy", 20.0)

        oco = client.params("order_oco_sell")
        self.assertEqual(float(oco["price"]), 50500.0)
        self.assertEqual(float(oco["stopPrice"]), 49500.0)
        self.assertEqual(oco["stopPrice"], oco["stopLimitPrice"])

    def test_short_oco_prices_straddle_entry(self):
        client = _Client(["FILLED"])
        bot = self.make_bot(client)

        bot.open_order("BTCUSDT", "sell", 20.0)

        oco = client.params("order_oco_buy")
        self.assertEqual(float(oco["price"]), 49500.0)
        self.assertEqual(float(oco["stopPrice"]), 50500.0)

    def test_unfilled_entry_is_cancelled_without_oco(self):
        client = _Client(["NEW"])
        bot = self.make_bot(client)

        result = bot.open_order("BTCUSDT", "buy", 20.0)

        self.assertFalse(result)
        self.assertIn("cancel_order", client.names())
        self.assertFalse([name for name in client.names() if name.startswith("order_oco")])
        self.assertGreaterEqual(self.clock, self.main.fill_timeout)

    def test_partial_fill_hedges_only_filled_quantity(self):
        client = _Client(["PARTIALLY_FILLED"], executed="0.00020000")
        bot = self.make_bot(client)

        self.assertTrue(bot.open_order("BTCUSDT", "buy", 20.0))

        self.assertEqual(client.params("order_oco_sell")["quantity"], "0.0002")
        self.assertIn("cancel_order", client.names())

    def test_terminal_rejection_places_no_oco(self):
        client = _Client(["REJECTED"])
        bot = self.make_bot(client)

        self.assertFalse(bot.open_order("BTCUSDT", "buy", 20.0))

        self.assertNotIn("cancel_order", client.names())
        self.assertFalse([name for name in client.names() if name.startswith("order_oco")])

    def test_unconfirmed_poll_assumes_position(self):
        client = _Client(["NEW"], fail_poll=True)
        bot = self.make_bot(client)

        self.assertTrue(bot.open_order("BTCUSDT", "buy", 20.0))

        self.assertFalse([name for name in client.names() if name.startswith("order_oco")])

    def test_oco_retries_before_succeeding(self):
        client = _Client(["FILLED"], fail_oco=1)
        bot = self.make_bot(client)

        self.assertTrue(bot.open_order("BTCUSDT", "buy", 20.0))

        self.assertEqual(client.names().count("order_oco_sell"), 2)
        self.assertNotIn("order_market", client.names())
        self.assertEqual(self.sleeps, [self.main.oco_retry_delay])

    def test_persistent_oco_failure_flattens_position(self):
        client = _Client(["FILLED"], fail_oco=99)
        bot = self.make_bot(client)

        self.assertFalse(bot.open_order("BTCUSDT", "buy", 20.0))

        self.assertEqual(client.names().count("order_oco_sell"), self.main.oco_attempts)
        self.assertEqual(client.params("order_market")["side"], "SELL")

    def test_flatten_failure_keeps_position_flag(self):
        client = _Client(["FILLED"], fail_oco=99, fail_flatten=True)
        bot = self.make_bot(client)

        self.assertTrue(bot.open_order("BTCUSDT", "buy", 20.0))

        self.assertIn("order_market", client.names())

    def test_dust_entry_is_not_submitted(self):
        client = _Client(["FILLED"])
        bot = self.make_bot(client)

        self.assertFalse(bot.open_order("BTCUSDT", "buy", 0.1))

        self.assertEqual(client.calls, [])

    def test_close_position_flips_side(self):
        client = _Client(["NEW"])
        bot = self.make_bot(client)
        client.calls.clear()

        bot.close_position("BTCUSDT", "BUY", 0.0004)

        self.assertEqual(client.params("order_market")["side"], "SELL")


if __name__ == "__main__":
    unittest.main()
