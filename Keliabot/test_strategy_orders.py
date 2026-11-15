"""Offline stub tests for the order sequencing in the strategy scripts.

Covers the Spot entry -> OCO flow in main.py and the market entry ->
reduce-only stop flow shared by ReasonSignal.py, BTCUSDT.py and test.py.
The scripts need python-binance, ta, pandas and numpy, so this module skips
itself when those imports fail instead of breaking a stdlib-only run.
"""
import importlib.util
import pathlib
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


class _FuturesClient:
    """Minimal Futures client stub; records calls and fails orders on demand."""

    def __init__(self, stop_failures=0, fail_flatten=False, price="50000.0", step="0.001"):
        self.stop_failures_left = stop_failures
        self.fail_flatten = fail_flatten
        self.price = price
        self.step = step
        self.calls = []
        self.exc = None

    def futures_symbol_ticker(self, **kwargs):
        return {"price": self.price}

    def futures_exchange_info(self):
        return {"symbols": [{"symbol": "BTCUSDT", "filters": [
            {"filterType": "PRICE_FILTER", "tickSize": "0.10"},
            {"filterType": "LOT_SIZE", "stepSize": self.step},
        ]}]}

    def futures_create_order(self, **kwargs):
        self.calls.append(("futures_create_order", kwargs))
        is_flatten = kwargs.get("type") == "MARKET" and kwargs.get("reduceOnly") == "true"
        if kwargs.get("type") == "STOP_MARKET" and self.stop_failures_left:
            self.stop_failures_left -= 1
            raise self.exc(-2021, "Order would immediately trigger.")
        if is_flatten and self.fail_flatten:
            raise self.exc(-2019, "Margin is insufficient.")
        return {"ok": kwargs.get("type")}

    def names(self):
        return [name for name, _ in self.calls]

    def orders(self, order_type):
        return [kwargs for _, kwargs in self.calls if kwargs.get("type") == order_type]


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


class FuturesProtectionTests(unittest.TestCase):
    """Retry-then-flatten stop protection shared by the three futures scripts."""

    SCRIPT_NAMES = ("ReasonSignal", "BTCUSDT", "test")

    @classmethod
    def setUpClass(cls):
        try:
            import binance_clients
        except ImportError as error:
            raise unittest.SkipTest(f"strategy dependencies unavailable: {error}")
        cls.binance_clients = binance_clients
        cls.modules = {}
        for name in cls.SCRIPT_NAMES:
            # Loaded by path because `test.py` would otherwise resolve to the
            # standard library `test` package.
            path = pathlib.Path(__file__).with_name(name + ".py")
            try:
                spec = importlib.util.spec_from_file_location(f"keliabot_{name.lower()}", path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
            except ImportError as error:
                raise unittest.SkipTest(f"strategy dependencies unavailable: {error}")
            cls.modules[name] = module

    def setUp(self):
        self.saved_allow_orders = self.binance_clients.ALLOW_ORDERS
        self.saved_sleeps = {name: module.sleep for name, module in self.modules.items()}
        self.binance_clients.ALLOW_ORDERS = True
        self.sleeps = []
        for module in self.modules.values():
            module.sleep = self.fake_sleep
        self.clock = 0.0

    def tearDown(self):
        self.binance_clients.ALLOW_ORDERS = self.saved_allow_orders
        for name, fake in self.saved_sleeps.items():
            self.modules[name].sleep = fake

    def fake_sleep(self, seconds):
        self.sleeps.append(seconds)
        self.clock += seconds

    def make_bot(self, module, client):
        client.exc = self.make_exc(module)
        bot = object.__new__(module.TradingBot)
        bot.client = client
        return bot

    def make_exc(self, module):
        def build(code, message):
            return module.BinanceAPIException(None, code, '{{"code":{},"msg":"{}"}}'.format(code, message))
        return build

    def test_long_entry_places_reduce_only_stop(self):
        for name, module in self.modules.items():
            with self.subTest(script=name):
                client = _FuturesClient()
                bot = self.make_bot(module, client)

                self.assertTrue(bot.open_order("BTCUSDT", "buy", module.volume))

                entry, stop = client.orders("MARKET")[0], client.orders("STOP_MARKET")[0]
                self.assertEqual(entry["side"], "BUY")
                self.assertEqual(stop["side"], "SELL")
                self.assertEqual(float(stop["stopPrice"]), 49500.0)
                self.assertEqual(stop["reduceOnly"], "true")
                self.assertEqual(float(stop["quantity"]), 0.002)

    def test_short_entry_places_reduce_only_stop(self):
        for name, module in self.modules.items():
            with self.subTest(script=name):
                client = _FuturesClient()
                bot = self.make_bot(module, client)

                bot.open_order("BTCUSDT", "sell", module.volume)

                stop = client.orders("STOP_MARKET")[0]
                self.assertEqual(stop["side"], "BUY")
                self.assertEqual(float(stop["stopPrice"]), 50500.0)
                self.assertEqual(stop["reduceOnly"], "true")

    def test_stop_retries_before_succeeding(self):
        for name, module in self.modules.items():
            with self.subTest(script=name):
                self.sleeps = []
                client = _FuturesClient(stop_failures=1)
                bot = self.make_bot(module, client)

                self.assertTrue(bot.open_order("BTCUSDT", "buy", module.volume))

                self.assertEqual(len(client.orders("STOP_MARKET")), 2)
                self.assertEqual(self.sleeps, [module.stop_retry_delay])

    def test_persistent_stop_failure_flattens_position(self):
        for name, module in self.modules.items():
            with self.subTest(script=name):
                client = _FuturesClient(stop_failures=99)
                bot = self.make_bot(module, client)

                self.assertFalse(bot.open_order("BTCUSDT", "buy", module.volume))

                self.assertEqual(len(client.orders("STOP_MARKET")), module.stop_attempts)
                flatten = client.orders("MARKET")[-1]
                self.assertEqual(flatten["side"], "SELL")
                self.assertEqual(flatten["reduceOnly"], "true")

    def test_flatten_failure_keeps_position_flag(self):
        for name, module in self.modules.items():
            with self.subTest(script=name):
                client = _FuturesClient(stop_failures=99, fail_flatten=True)
                bot = self.make_bot(module, client)

                self.assertTrue(bot.open_order("BTCUSDT", "buy", module.volume))

    def test_sub_min_notional_entry_skips_stop(self):
        module = self.modules["ReasonSignal"]
        client = _FuturesClient()
        bot = self.make_bot(module, client)

        self.assertTrue(bot.open_order("BTCUSDT", "buy", 5.0))

        self.assertEqual(len(client.orders("MARKET")), 1)
        self.assertEqual(client.orders("STOP_MARKET"), [])

    def test_close_position_reports_outcome(self):
        for name, module in self.modules.items():
            with self.subTest(script=name):
                client = _FuturesClient()
                bot = self.make_bot(module, client)

                self.assertTrue(bot.close_position("BTCUSDT", "BUY", 0.002))
                self.assertFalse(self.make_bot(module, _FuturesClient(fail_flatten=True))
                                 .close_position("BTCUSDT", "BUY", 0.002))


if __name__ == "__main__":
    unittest.main()
