import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from fetch_market_data import fetch_klines, parse_utc, save_csv


class MarketDataDownloaderTests(unittest.TestCase):
    def test_parse_utc_date(self):
        self.assertEqual(
            parse_utc("2026-01-01"),
            int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp() * 1000),
        )

    def test_rejects_invalid_interval_without_network_call(self):
        with self.assertRaises(ValueError):
            fetch_klines("BTCUSDT", "1h", 1, 2)

    def test_rejects_invalid_date_range(self):
        with self.assertRaises(ValueError):
            fetch_klines("BTCUSDT", "1m", 2, 2)

    def test_saves_backtester_compatible_csv(self):
        rows = [[1, "10", "12", "9", "11", "100", 2]]
        with TemporaryDirectory() as folder:
            path = save_csv(rows, Path(folder) / "candles.csv")
            content = path.read_text(encoding="utf-8")
            self.assertIn("open_time,open,high,low,close,volume,close_time", content)
            self.assertIn("1,10,12,9,11,100,2", content)


if __name__ == "__main__":
    unittest.main()
