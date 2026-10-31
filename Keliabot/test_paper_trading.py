import unittest
from decimal import Decimal
from paper_trading import PaperTradingAccount


class PaperTradingAccountTests(unittest.TestCase):
    def test_buy_and_mark_to_market(self):
        account = PaperTradingAccount("1000", "0.001")
        account.execute("buy", "0.1", "100")
        result = account.summary("110")
        self.assertEqual(result["cash"], Decimal("989.9900"))
        self.assertEqual(result["asset_quantity"], Decimal("0.1"))
        self.assertEqual(result["equity"], Decimal("1000.9900"))

    def test_sell_reduces_asset_and_adds_proceeds(self):
        account = PaperTradingAccount("1000")
        account.execute("buy", "1", "100")
        account.execute("sell", "0.4", "120")
        self.assertEqual(account.asset_quantity, Decimal("0.6"))
        self.assertEqual(account.cash, Decimal("947.85200"))

    def test_rejects_overspending(self):
        account = PaperTradingAccount("10")
        with self.assertRaises(ValueError):
            account.execute("buy", "1", "11")

    def test_rejects_overselling(self):
        account = PaperTradingAccount("100")
        with self.assertRaises(ValueError):
            account.execute("sell", "1", "10")

    def test_rejects_invalid_side_and_zero_values(self):
        account = PaperTradingAccount()
        for side, qty, price in [("hold", "1", "10"), ("buy", "0", "10"), ("buy", "1", "0")]:
            with self.subTest(side=side, qty=qty, price=price):
                with self.assertRaises(ValueError):
                    account.execute(side, qty, price)


if __name__ == "__main__":
    unittest.main()
