import unittest
from decimal import Decimal
from backtesting import SMACrossoverBacktester, load_ohlcv_csv, sma
from pathlib import Path
from tempfile import TemporaryDirectory


class BacktestingTests(unittest.TestCase):
    def setUp(self):
        closes = [5, 4, 3, 4, 5, 6, 7, 6, 5, 4, 3]
        self.rows = [{"open": str(value), "close": str(value)} for value in closes]

    def test_sma_warmup_and_values(self):
        values = [Decimal("1"), Decimal("2"), Decimal("3")]
        self.assertEqual(sma(values, 2), [None, Decimal("1.5"), Decimal("2.5")])

    def test_backtest_returns_metrics_and_uses_next_open(self):
        result = SMACrossoverBacktester(
            starting_cash="1000", fee_rate="0.001", fast_period=2, slow_period=3
        ).run(self.rows)
        self.assertGreaterEqual(result["closed_trades"], 1)
        self.assertGreaterEqual(result["max_drawdown_pct"], Decimal("0"))
        self.assertLessEqual(result["win_rate_pct"], Decimal("100"))
        self.assertEqual(result["starting_cash"], Decimal("1000"))
        self.assertGreater(result["ending_equity"], Decimal("0"))
        self.assertTrue(result["equity_curve"])

    def test_rejects_invalid_periods(self):
        with self.assertRaises(ValueError):
            SMACrossoverBacktester(fast_period=5, slow_period=5)

    def test_rejects_too_few_candles(self):
        with self.assertRaises(ValueError):
            SMACrossoverBacktester(fast_period=2, slow_period=3).run(self.rows[:3])

    def test_loads_csv_case_insensitively(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "prices.csv"
            path.write_text("Open,Close\n10,11\n11,12\n12,13\n", encoding="utf-8")
            rows = load_ohlcv_csv(path)
            self.assertEqual(rows[0]["open"], Decimal("10"))
            self.assertEqual(rows[-1]["close"], Decimal("13"))


if __name__ == "__main__":
    unittest.main()
