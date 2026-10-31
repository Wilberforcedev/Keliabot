import unittest
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from backtesting import SMACrossoverBacktester
from compare_timeframes import build_report, compare_files


class TimeframeComparisonTests(unittest.TestCase):
    def setUp(self):
        closes = [5, 4, 3, 4, 5, 6, 7, 6, 5, 4, 3, 4, 5, 6]
        self.rows = [{"open": str(value), "close": str(value)} for value in closes]

    def test_builds_html_report_with_metrics_and_chart(self):
        result = SMACrossoverBacktester(
            starting_cash="1000", fast_period=2, slow_period=3
        ).run(self.rows)
        with TemporaryDirectory() as folder:
            output = build_report(
                {"1m": result, "5m": result},
                Path(folder) / "comparison.html",
                {"starting_cash": "1000", "fast_period": 2, "slow_period": 3},
            )
            report = output.read_text(encoding="utf-8")
            self.assertIn("Equity curves", report)
            self.assertIn("Max drawdown", report)
            self.assertIn("Highest historical return", report)
            self.assertIn('"name":"1m"', report)

    def test_compare_files_uses_identical_parameters(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "sample.csv"
            path.write_text(
                "open,close\n" + "".join(f"{r['open']},{r['close']}\n" for r in self.rows),
                encoding="utf-8",
            )
            results = compare_files({"1m": path, "5m": path}, fast_period=2, slow_period=3)
            self.assertEqual(set(results), {"1m", "5m"})
            self.assertEqual(results["1m"]["ending_equity"], results["5m"]["ending_equity"])

    def test_rejects_empty_results(self):
        with TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                build_report({}, Path(folder) / "empty.html")


if __name__ == "__main__":
    unittest.main()
