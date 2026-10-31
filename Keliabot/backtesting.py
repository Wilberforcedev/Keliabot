"""Deterministic, offline OHLCV backtester. No exchange/API calls are made."""
import csv
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path


def _decimal(value, label):
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError):
        raise ValueError(f"{label} must be numeric")
    if not number.is_finite() or number <= 0:
        raise ValueError(f"{label} must be finite and greater than zero")
    return number


def load_ohlcv_csv(path):
    """Load CSV rows containing at least open and close columns (case-insensitive)."""
    with Path(path).open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError("CSV must contain a header row")
        names = {name.strip().lower(): name for name in reader.fieldnames}
        if "open" not in names or "close" not in names:
            raise ValueError("CSV must contain open and close columns")
        rows = []
        for line_number, row in enumerate(reader, start=2):
            rows.append({
                "open": _decimal(row[names["open"]], f"line {line_number} open"),
                "close": _decimal(row[names["close"]], f"line {line_number} close"),
            })
    if len(rows) < 3:
        raise ValueError("At least three OHLCV rows are required")
    return rows


def sma(values, period):
    if period < 1:
        raise ValueError("SMA period must be positive")
    result = [None] * len(values)
    for index in range(period - 1, len(values)):
        result[index] = sum(values[index - period + 1:index + 1]) / Decimal(period)
    return result


@dataclass
class CompletedTrade:
    entry_price: Decimal
    exit_price: Decimal
    quantity: Decimal
    entry_fee: Decimal
    exit_fee: Decimal
    net_pnl: Decimal


class SMACrossoverBacktester:
    """Long-only spot SMA crossover; signals execute at the following candle open."""
    def __init__(self, starting_cash="1000", fee_rate="0.001", fast_period=9, slow_period=26, allocation="0.95"):
        self.starting_cash = _decimal(starting_cash, "starting_cash")
        self.fee_rate = Decimal(str(fee_rate))
        self.allocation = Decimal(str(allocation))
        if not self.fee_rate.is_finite() or not Decimal("0") <= self.fee_rate < Decimal("1"):
            raise ValueError("fee_rate must be between 0 (inclusive) and 1 (exclusive)")
        if not self.allocation.is_finite() or not Decimal("0") < self.allocation <= Decimal("1"):
            raise ValueError("allocation must be greater than 0 and at most 1")
        if not isinstance(fast_period, int) or not isinstance(slow_period, int) or fast_period < 1 or slow_period <= fast_period:
            raise ValueError("periods must be integers with 1 <= fast_period < slow_period")
        self.fast_period = fast_period
        self.slow_period = slow_period

    def run(self, rows):
        if len(rows) <= self.slow_period:
            raise ValueError("Not enough candles for the selected slow SMA period")
        opens = [_decimal(row["open"], "open") for row in rows]
        closes = [_decimal(row["close"], "close") for row in rows]
        fast = sma(closes, self.fast_period)
        slow = sma(closes, self.slow_period)
        cash = self.starting_cash
        quantity = Decimal("0")
        entry_cost = Decimal("0")
        entry_price = None
        entry_fee = Decimal("0")
        trades = []
        equity_curve = []
        peak = self.starting_cash
        max_drawdown = Decimal("0")

        # A crossover observed at candle i is filled at candle i+1 open.
        for index in range(1, len(rows) - 1):
            previous_ready = fast[index - 1] is not None and slow[index - 1] is not None
            current_ready = fast[index] is not None and slow[index] is not None
            if not (previous_ready and current_ready):
                continue
            crossed_up = fast[index - 1] <= slow[index - 1] and fast[index] > slow[index]
            crossed_down = fast[index - 1] >= slow[index - 1] and fast[index] < slow[index]
            fill_price = opens[index + 1]

            if crossed_up and quantity == 0:
                spend = cash * self.allocation
                fee = spend * self.fee_rate
                quantity = (spend - fee) / fill_price
                if quantity > 0:
                    cash -= spend
                    entry_cost = spend
                    entry_price = fill_price
                    entry_fee = fee
            elif crossed_down and quantity > 0:
                proceeds = quantity * fill_price
                exit_fee = proceeds * self.fee_rate
                cash += proceeds - exit_fee
                net_pnl = proceeds - exit_fee - entry_cost
                trades.append(CompletedTrade(entry_price, fill_price, quantity, entry_fee, exit_fee, net_pnl))
                quantity = Decimal("0")
                entry_cost = Decimal("0")
                entry_price = None
                entry_fee = Decimal("0")

            mark = closes[index + 1]
            equity = cash + quantity * mark
            equity_curve.append(equity)
            peak = max(peak, equity)
            drawdown = (peak - equity) / peak if peak else Decimal("0")
            max_drawdown = max(max_drawdown, drawdown)

        final_price = closes[-1]
        final_equity = cash + quantity * final_price
        # Include any still-open position in ending equity; do not fabricate a closing trade.
        peak = max(peak, final_equity)
        if peak:
            max_drawdown = max(max_drawdown, (peak - final_equity) / peak)
        winners = sum(1 for trade in trades if trade.net_pnl > 0)
        total_return = (final_equity - self.starting_cash) / self.starting_cash
        return {
            "starting_cash": self.starting_cash,
            "ending_equity": final_equity,
            "net_pnl": final_equity - self.starting_cash,
            "total_return_pct": total_return * Decimal("100"),
            "closed_trades": len(trades),
            "winning_trades": winners,
            "win_rate_pct": (Decimal(winners) / Decimal(len(trades)) * Decimal("100")) if trades else Decimal("0"),
            "max_drawdown_pct": max_drawdown * Decimal("100"),
            "open_position_quantity": quantity,
            "trades": trades,
            "equity_curve": equity_curve,
        }
