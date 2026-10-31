"""Offline paper-trading simulator. This module never contacts an exchange."""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import List


@dataclass(frozen=True)
class Trade:
    side: str
    quantity: Decimal
    price: Decimal
    fee: Decimal


class PaperTradingAccount:
    def __init__(self, starting_cash="1000", fee_rate="0.001"):
        self.cash = self._positive_or_zero(starting_cash, "starting_cash")
        self.fee_rate = self._positive_or_zero(fee_rate, "fee_rate")
        if self.fee_rate >= 1:
            raise ValueError("fee_rate must be less than 1")
        self.asset_quantity = Decimal("0")
        self.trades: List[Trade] = []

    @staticmethod
    def _positive_or_zero(value, field):
        try:
            number = Decimal(str(value))
        except (InvalidOperation, TypeError):
            raise ValueError(f"{field} must be a valid number")
        if not number.is_finite() or number < 0:
            raise ValueError(f"{field} must be finite and non-negative")
        return number

    def execute(self, side, quantity, price):
        side = str(side).strip().lower()
        qty = self._positive_or_zero(quantity, "quantity")
        px = self._positive_or_zero(price, "price")
        if side not in ("buy", "sell"):
            raise ValueError("side must be 'buy' or 'sell'")
        if qty == 0 or px == 0:
            raise ValueError("quantity and price must be greater than zero")
        notional = qty * px
        fee = notional * self.fee_rate
        if side == "buy":
            total = notional + fee
            if total > self.cash:
                raise ValueError("Insufficient paper cash for this buy")
            self.cash -= total
            self.asset_quantity += qty
        else:
            if qty > self.asset_quantity:
                raise ValueError("Insufficient paper asset quantity for this sell")
            self.cash += notional - fee
            self.asset_quantity -= qty
        trade = Trade(side, qty, px, fee)
        self.trades.append(trade)
        return trade

    def summary(self, mark_price):
        mark = self._positive_or_zero(mark_price, "mark_price")
        if mark == 0:
            raise ValueError("mark_price must be greater than zero")
        market_value = self.asset_quantity * mark
        return {
            "cash": self.cash,
            "asset_quantity": self.asset_quantity,
            "market_value": market_value,
            "equity": self.cash + market_value,
            "trade_count": len(self.trades),
        }
